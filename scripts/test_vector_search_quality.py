"""
벡터 검색 품질 테스트 스크립트

사용법:
    python scripts/test_vector_search_quality.py <bot_id> "<query>"

예시:
    python scripts/test_vector_search_quality.py bot_123 "사용자 가이드는 어디에 있나요?"

목적:
    - 특정 봇의 벡터 검색 품질 확인
    - 유사도 점수 분석
    - 검색된 청크 미리보기
"""
import asyncio
import sys
from app.core.database import get_async_session_context
from app.services.vector_service import VectorService
from sqlalchemy import select
from app.models.bot import Bot


async def test_search(bot_id: str, query: str, top_k: int = 5):
    """벡터 검색 품질 테스트"""
    async with get_async_session_context() as db:
        # 봇 존재 여부 확인
        result = await db.execute(
            select(Bot).where(Bot.bot_id == bot_id)
        )
        bot = result.scalar_one_or_none()
        
        if not bot:
            print(f"❌ 봇을 찾을 수 없습니다: {bot_id}\n")
            return False
        
        print(f"{'='*80}")
        print(f"벡터 검색 품질 테스트")
        print(f"{'='*80}\n")
        print(f"봇 ID: {bot_id}")
        print(f"봇 이름: {bot.name}")
        print(f"질문: {query}")
        print(f"검색 개수 (top_k): {top_k}\n")
        
        service = VectorService()
        
        try:
            results = await service.search_similar_chunks(
                bot_id=bot_id,
                query=query,
                top_k=top_k,
                db=db
            )
            
            if not results:
                print("❌ 검색 결과가 없습니다.")
                print("\n가능한 원인:")
                print("  1. 업로드된 문서가 없음")
                print("  2. 문서 임베딩이 아직 진행 중")
                print("  3. 쿼리와 관련된 문서가 없음\n")
                return False
            
            print(f"✅ 검색 결과: {len(results)}개\n")
            print(f"{'='*80}\n")
            
            for i, result in enumerate(results, 1):
                content = result["content"]
                similarity = result["similarity"]
                metadata = result["metadata"]
                
                print(f"[{i}] 유사도: {similarity:.3f} {'🟢' if similarity >= 0.7 else '🟡' if similarity >= 0.5 else '🔴'}")
                print(f"{'─'*80}")
                print(f"    파일명: {metadata.get('original_filename', metadata.get('filename', 'Unknown'))}")
                print(f"    청크 인덱스: {metadata.get('chunk_index', 'Unknown')}")
                print(f"    청크 ID: {metadata.get('chunk_id', 'Unknown')}")
                print(f"    문서 ID: {metadata.get('document_id', 'Unknown')}")
                print(f"    생성일: {metadata.get('created_at', 'Unknown')}")
                print(f"\n    내용 미리보기:")
                print(f"    {content[:300]}{'...' if len(content) > 300 else ''}")
                print(f"\n    전체 길이: {len(content)} chars\n")
            
            print(f"{'='*80}\n")
            
            # 통계 계산
            similarities = [r["similarity"] for r in results]
            avg_similarity = sum(similarities) / len(similarities)
            max_similarity = max(similarities)
            min_similarity = min(similarities)
            
            print(f"📊 검색 품질 통계")
            print(f"{'─'*80}")
            print(f"    평균 유사도: {avg_similarity:.3f}")
            print(f"    최고 유사도: {max_similarity:.3f}")
            print(f"    최저 유사도: {min_similarity:.3f}")
            print(f"    총 컨텍스트 길이: {sum(len(r['content']) for r in results)} chars\n")
            
            # 품질 평가
            print(f"💡 품질 평가")
            print(f"{'─'*80}")
            
            if avg_similarity >= 0.7:
                print("    ✅ 우수: 검색 품질이 매우 좋습니다.")
            elif avg_similarity >= 0.5:
                print("    🟡 보통: 검색 품질이 양호합니다.")
                print("    → 더 구체적인 질문을 하면 정확도가 향상될 수 있습니다.")
            else:
                print("    🔴 낮음: 검색 품질이 낮습니다.")
                print("    → 다음 사항을 확인하세요:")
                print("      1. 질문이 문서 내용과 관련이 있는지")
                print("      2. 청킹 파라미터가 적절한지 (현재: chunk_size=1000)")
                print("      3. 문서가 올바르게 파싱되었는지")
            
            print()
            
            if max_similarity >= 0.8:
                print("    ✅ 가장 관련성 높은 청크의 유사도가 매우 높습니다.")
            elif max_similarity >= 0.6:
                print("    🟡 가장 관련성 높은 청크의 유사도가 양호합니다.")
            else:
                print("    🔴 가장 관련성 높은 청크의 유사도도 낮습니다.")
                print("    → 문서에 관련 정보가 없거나, 쿼리 표현을 바꿔보세요.")
            
            print()
            
            return True
            
        except Exception as e:
            print(f"❌ 검색 중 오류 발생: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


async def show_bot_documents(bot_id: str):
    """봇에 업로드된 문서 목록 표시"""
    from sqlalchemy import select, func
    from app.models.document import Document
    from app.models.document_embeddings import DocumentEmbedding
    
    async with get_async_session_context() as db:
        # 문서 개수 조회
        doc_result = await db.execute(
            select(func.count(Document.document_id))
            .where(Document.bot_id == bot_id)
        )
        doc_count = doc_result.scalar_one()
        
        # 임베딩 개수 조회
        emb_result = await db.execute(
            select(func.count(DocumentEmbedding.id))
            .where(DocumentEmbedding.bot_id == bot_id)
        )
        emb_count = emb_result.scalar_one()
        
        print(f"\n📚 봇의 문서 정보")
        print(f"{'─'*80}")
        print(f"    업로드된 문서: {doc_count}개")
        print(f"    임베딩된 청크: {emb_count}개")
        
        if doc_count == 0:
            print(f"\n    ⚠️ 업로드된 문서가 없습니다.")
            print(f"    → 프론트엔드에서 문서를 업로드하세요.\n")
        elif emb_count == 0:
            print(f"\n    ⚠️ 임베딩된 청크가 없습니다.")
            print(f"    → 문서 처리가 진행 중이거나 실패했을 수 있습니다.")
            print(f"    → documents 테이블의 status를 확인하세요.\n")
        else:
            avg_chunks_per_doc = emb_count / doc_count if doc_count > 0 else 0
            print(f"    문서당 평균 청크: {avg_chunks_per_doc:.1f}개\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python test_vector_search_quality.py <bot_id> [query] [top_k]")
        print("\n예시:")
        print('  python test_vector_search_quality.py bot_123')
        print('  python test_vector_search_quality.py bot_123 "사용자 가이드는 어디에 있나요?"')
        print('  python test_vector_search_quality.py bot_123 "가격 정책" 10')
        print()
        sys.exit(1)
    
    bot_id = sys.argv[1]
    
    if len(sys.argv) < 3:
        # 쿼리가 없으면 문서 정보만 표시
        asyncio.run(show_bot_documents(bot_id))
    else:
        query = sys.argv[2]
        top_k = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        
        try:
            success = asyncio.run(test_search(bot_id, query, top_k))
            if success:
                asyncio.run(show_bot_documents(bot_id))
            sys.exit(0 if success else 1)
        except KeyboardInterrupt:
            print("\n\n중단되었습니다.")
            sys.exit(0)
        except Exception as e:
            print(f"\n❌ 예기치 않은 오류: {str(e)}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

