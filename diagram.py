"""
나만무 Backend 실제 AWS 인프라 아키텍처 다이어그램

실제 배포된 리소스 정보:
- VPC: vpc-0029eae8faf24a6aa (10.0.0.0/16) - RAG-VPC-Seoul
- Public Subnets:
  * subnet-059a3f0c921dd5f01 (10.0.1.0/24, ap-northeast-2a) - RAG-Public-2a
  * subnet-08e5dd9ed71e1d6dd (10.0.2.0/24, ap-northeast-2c) - RAG-Public-2c
- Private Subnets:
  * subnet-06652259d983dbb7d (10.0.11.0/24, ap-northeast-2a) - RAG-Private-2a
  * subnet-084722ea7ba3c2f54 (10.0.12.0/24, ap-northeast-2c) - RAG-Private-2c
- Internet Gateway: igw-0d1d3acf69dd263ec
- NAT Gateway: nat-0a8cd454c39cf2486 (Public Subnet 2a에 위치)
- ALB: RAG-ALB-Seoul (Public Subnets에 배포)
- ECS: rag-cluster/rag-backend-service (Private Subnets에 배포)
- Aurora: rag-aurora-cluster (Private Subnets의 DB 서브넷 그룹 사용)
- ElastiCache: rag-redis (Private Subnets 사용)
"""
from diagrams import Cluster, Diagram
from diagrams.aws.network import ELB, NATGateway, InternetGateway
from diagrams.aws.database import RDS, ElastiCache
from diagrams.aws.storage import S3
from diagrams.aws.integration import SQS
from diagrams.aws.management import Cloudwatch
from diagrams.aws.compute import ECS
from diagrams.programming.framework import FastAPI
from diagrams.programming.language import Python
from diagrams.onprem.client import User
from diagrams.generic.os import Ubuntu

with Diagram("나만무 Backend 아키텍처 (실제 AWS 인프라)", filename="backend_architecture", show=False, direction="TB"):
    
    # 외부 사용자
    user = User("Widget / Widget SDK / UI\n(Internet)")
    
    # VPC 구조
    with Cluster("VPC: RAG-VPC-Seoul\nvpc-0029eae8faf24a6aa\n(10.0.0.0/16)"):
        
        # Internet Gateway (VPC 진입점)
        igw = InternetGateway("Internet Gateway\nigw-0d1d3acf69dd263ec")
        user >> igw
        
        # Public Subnets (ALB, NAT Gateway)
        with Cluster("Public Subnets\n(Internet-facing)"):
            with Cluster("Public Subnet 2a\nsubnet-059a3f0c921dd5f01\n10.0.1.0/24"):
                nat_gw = NATGateway("NAT Gateway\nnat-0a8cd454c39cf2486")
            
            with Cluster("Public Subnet 2c\nsubnet-08e5dd9ed71e1d6dd\n10.0.2.0/24"):
                pass
            
            # ALB는 2개 AZ에 분산 배포
            alb = ELB("RAG-ALB-Seoul\nsg-01b326d770b46ac95\napi.snapagent.store")
        
        igw >> alb
        
        # Private Subnets (ECS, Database)
        with Cluster("Private Subnets\n(Isolated)"):
            with Cluster("Private Subnet 2a\nsubnet-06652259d983dbb7d\n10.0.11.0/24"):
                # ECS Fargate Service
                with Cluster("ECS Fargate\nrag-cluster/rag-backend-service"):
                    ecs_task_2a = ECS("Backend Task\n(.5 vCPU, 1GB)\nARM64")
                    fastapi_app = FastAPI("FastAPI API\nPort: 8001")
                    ecs_task_2a >> fastapi_app
                
                # Database Resources (Private Subnet에 배포)
                database = RDS("Aurora PostgreSQL 16\nrag-aurora-cluster\npgvector extension\nsg-08affcfa97baaeac1")
                cache = ElastiCache("ElastiCache Redis\nrag-redis\nTLS enabled\nsg-08affcfa97baaeac1")
            
            with Cluster("Private Subnet 2c\nsubnet-084722ea7ba3c2f54\n10.0.12.0/24"):
                ecs_task_2c = ECS("Backend Task 2c\n(.5 vCPU, 1GB)\nARM64")
                
                # Embedding Worker
                with Cluster("Embedding Worker"):
                    worker = Ubuntu("EmbeddingWorker\n(SQS Consumer)")
                    document_processor = Python("DocumentProcessor\nChunker")
                
                ecs_task_2c >> worker
                worker >> document_processor
        
        # AWS Managed Services (VPC 외부, 엔드포인트로 접근)
        with Cluster("AWS Managed Services"):
            s3 = S3("S3 문서 저장소\nDocument Storage")
            sqs = SQS("SQS 문서 큐\nDocument Queue\n+ DLQ")
            bedrock = Cloudwatch("AWS Bedrock\nTitan Embedding\nClaude Haiku 4.5")
            cost_monitoring = Cloudwatch("CloudWatch Logs\n/ecs/rag-backend\nCost Monitoring")
        
        # 네트워크 플로우
        # Internet -> IGW -> ALB -> ECS Tasks
        alb >> ecs_task_2a
        alb >> ecs_task_2c
        
        # Private Subnet -> NAT Gateway -> IGW (아웃바운드 인터넷)
        ecs_task_2a >> nat_gw >> igw
        ecs_task_2c >> nat_gw
        
        # FastAPI -> 데이터베이스/캐시
        fastapi_app >> cache
        fastapi_app >> database
        
        # FastAPI -> AWS 서비스 (NAT Gateway 통해)
        fastapi_app >> s3
        fastapi_app >> sqs
        fastapi_app >> bedrock
        fastapi_app >> cost_monitoring
        
        # API Domains (논리적 그룹)
        with Cluster("FastAPI API Domains"):
            auth = FastAPI("인증 / OAuth")
            bots = FastAPI("봇 관리 / 배포")
            workflows = FastAPI("워크플로우 / 버전")
            documents = FastAPI("문서 / 챗 / 지식")
            widget = FastAPI("Widget / SDK")
        
        fastapi_app >> auth
        fastapi_app >> bots
        fastapi_app >> workflows
        fastapi_app >> documents
        fastapi_app >> widget
        
        # Embedding Worker 플로우
        # SQS -> Worker -> S3 다운로드 -> 처리 -> DB 저장
        sqs >> worker
        worker >> s3
        worker >> document_processor >> database
        worker >> bedrock
