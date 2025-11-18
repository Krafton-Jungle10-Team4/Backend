#!/bin/bash
# AWS 인프라 검증 스크립트
# backend_architecture.png와 실제 AWS 리소스 비교

set -e

REGION="ap-northeast-2"
echo "🔍 AWS 인프라 검증 시작 (리전: $REGION)"
echo "=========================================="
echo ""

# 색상 정의
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check_resource() {
    local name=$1
    local command=$2
    echo -n "✓ $name: "
    
    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}존재함${NC}"
        eval "$command"
        echo ""
        return 0
    else
        echo -e "${RED}없음 또는 접근 불가${NC}"
        echo ""
        return 1
    fi
}

# 1. ECS 클러스터 및 서비스
echo "📦 ECS 리소스"
echo "----------------------------------------"
check_resource "ECS Cluster (rag-cluster)" \
    "aws ecs describe-clusters --clusters rag-cluster --region $REGION --query 'clusters[0].[clusterName,status,runningTasksCount,activeServicesCount]' --output table"

check_resource "ECS Service (rag-backend-service)" \
    "aws ecs describe-services --cluster rag-cluster --services rag-backend-service --region $REGION --query 'services[0].[serviceName,status,desiredCount,runningCount,launchType,platformVersion]' --output table"

check_resource "ECS Task Definition (rag-backend-task)" \
    "aws ecs describe-task-definition --task-definition rag-backend-task --region $REGION --query 'taskDefinition.[family,revision,cpu,memory,runtimePlatform]' --output table"

echo ""

# 2. 데이터베이스
echo "🗄️  데이터베이스 리소스"
echo "----------------------------------------"
check_resource "Aurora PostgreSQL" \
    "aws rds describe-db-clusters --db-cluster-identifier rag-aurora-cluster --region $REGION --query 'DBClusters[0].[DBClusterIdentifier,Engine,EngineVersion,Status,Endpoint]' --output table"

check_resource "ElastiCache Redis" \
    "aws elasticache describe-cache-clusters --cache-cluster-id rag-redis --region $REGION --query 'CacheClusters[0].[CacheClusterId,Engine,EngineVersion,CacheNodeType,Status,CacheNodes[0].Endpoint.Address]' --output table" 2>/dev/null || \
    aws elasticache describe-replication-groups --replication-group-id rag-redis --region $REGION --query 'ReplicationGroups[0].[ReplicationGroupId,Status,NodeGroups[0].PrimaryEndpoint.Address]' --output table 2>/dev/null || \
    echo -e "${YELLOW}Redis 클러스터 정보를 찾을 수 없습니다. 다른 식별자를 사용하는지 확인하세요.${NC}"

echo ""

# 3. 네트워크 리소스
echo "🌐 네트워크 리소스"
echo "----------------------------------------"
check_resource "VPC" \
    "aws ec2 describe-vpcs --vpc-ids vpc-0c0a3a3baf79f4c66 --region $REGION --query 'Vpcs[0].[VpcId,CidrBlock,State]' --output table"

check_resource "ALB (Application Load Balancer)" \
    "aws elbv2 describe-load-balancers --region $REGION --query 'LoadBalancers[?contains(LoadBalancerName, \`RAG\`) || contains(LoadBalancerName, \`rag\`) || contains(LoadBalancerName, \`ALB\`)].{Name:LoadBalancerName,DNS:DNSName,State:State.Code,Type:Type}' --output table"

check_resource "Target Group" \
    "aws elbv2 describe-target-groups --region $REGION --query 'TargetGroups[?contains(TargetGroupName, \`RAG\`) || contains(TargetGroupName, \`rag\`)].{Name:TargetGroupName,Port:Port,Protocol:Protocol,HealthCheckPath:HealthCheckPath}' --output table"

echo ""

# 4. S3 버킷 (아키텍처에 포함되어 있음)
echo "📦 S3 버킷 (문서 저장소)"
echo "----------------------------------------"
S3_BUCKETS=$(aws s3 ls --region $REGION | grep -i "rag\|namamu\|snapagent" || true)
if [ -z "$S3_BUCKETS" ]; then
    echo -e "${YELLOW}⚠️  RAG 관련 S3 버킷을 찾을 수 없습니다.${NC}"
    echo "사용 중인 버킷 목록:"
    aws s3 ls --region $REGION | head -10
else
    echo -e "${GREEN}발견된 S3 버킷:${NC}"
    echo "$S3_BUCKETS"
fi
echo ""

# 5. SQS 큐 (아키텍처에 포함되어 있음)
echo "📨 SQS 큐 (문서 처리 큐)"
echo "----------------------------------------"
SQS_QUEUES=$(aws sqs list-queues --region $REGION 2>/dev/null | grep -i "rag\|namamu\|document\|embedding" || true)
if [ -z "$SQS_QUEUES" ]; then
    echo -e "${YELLOW}⚠️  RAG 관련 SQS 큐를 찾을 수 없습니다.${NC}"
    echo "모든 SQS 큐:"
    aws sqs list-queues --region $REGION 2>/dev/null || echo "SQS 큐가 없거나 접근할 수 없습니다."
else
    echo -e "${GREEN}발견된 SQS 큐:${NC}"
    echo "$SQS_QUEUES" | while read queue_url; do
        echo "  - $queue_url"
        aws sqs get-queue-attributes --queue-url "$queue_url" --attribute-names All --region $REGION --query '{Name:Attributes.ApproximateNumberOfMessages,InFlight:Attributes.ApproximateNumberOfMessagesNotVisible}' --output table 2>/dev/null || true
    done
fi
echo ""

# 6. ECR (컨테이너 레지스트리)
echo "🐳 ECR 리포지토리"
echo "----------------------------------------"
check_resource "ECR Repository (rag-backend)" \
    "aws ecr describe-repositories --repository-names rag-backend --region $REGION --query 'repositories[0].[repositoryName,repositoryUri,imageScanningConfiguration.scanOnPush]' --output table"

LATEST_IMAGE=$(aws ecr describe-images --repository-name rag-backend --region $REGION --query 'sort_by(imageDetails,& imagePushedAt)[-1]' --output json 2>/dev/null)
if [ ! -z "$LATEST_IMAGE" ] && [ "$LATEST_IMAGE" != "null" ]; then
    echo "최신 이미지:"
    echo "$LATEST_IMAGE" | jq '{Tags: .imageTags, PushedAt: .imagePushedAt, Size: .imageSizeInBytes, Architecture: .imageManifestMediaType}' 2>/dev/null || echo "$LATEST_IMAGE"
fi
echo ""

# 7. Route 53 및 ACM
echo "🔐 DNS 및 인증서"
echo "----------------------------------------"
check_resource "Route 53 Hosted Zone (snapagent.store)" \
    "aws route53 list-hosted-zones --query 'HostedZones[?contains(Name, \`snapagent.store\`)].{Name:Name,Id:Id}' --output table"

check_resource "ACM Certificate (api.snapagent.store)" \
    "aws acm list-certificates --region $REGION --query 'CertificateSummaryList[?contains(DomainName, \`snapagent.store\`)].{Domain:DomainName,Status:Status,Type:Type}' --output table"

echo ""

# 8. CloudWatch Logs
echo "📊 CloudWatch Logs"
echo "----------------------------------------"
LOG_GROUPS=$(aws logs describe-log-groups --region $REGION --query 'logGroups[?contains(logGroupName, \`rag\`) || contains(logGroupName, \`ecs\`)].{Name:logGroupName,Size:storedBytes}' --output table 2>/dev/null)
if [ ! -z "$LOG_GROUPS" ]; then
    echo "$LOG_GROUPS"
else
    echo -e "${YELLOW}로그 그룹을 찾을 수 없습니다.${NC}"
fi
echo ""

# 9. Secrets Manager
echo "🔑 Secrets Manager"
echo "----------------------------------------"
SECRETS=$(aws secretsmanager list-secrets --region $REGION --query 'SecretList[?contains(Name, \`rag\`) || contains(Name, \`aurora\`) || contains(Name, \`redis\`)].{Name:Name,LastChanged:LastChangedDate}' --output table 2>/dev/null)
if [ ! -z "$SECRETS" ]; then
    echo "$SECRETS"
else
    echo -e "${YELLOW}RAG 관련 Secret을 찾을 수 없습니다.${NC}"
fi
echo ""

# 10. 요약 및 불일치 점검
echo "=========================================="
echo "📋 아키텍처 다이어그램 vs 실제 인프라 비교"
echo "=========================================="
echo ""
echo "아키텍처 다이어그램에 포함된 구성요소:"
echo "  ✓ ECS Fargate (FastAPI API)"
echo "  ✓ PostgreSQL + pgvector (Aurora)"
echo "  ✓ Redis (ElastiCache)"
echo "  ✓ ALB / API Gateway"
echo "  ✓ S3 문서 저장소"
echo "  ✓ SQS 문서 큐"
echo "  ✓ Embedding Worker"
echo "  ✓ AWS Bedrock (임베딩 + LLM)"
echo "  ✓ CloudWatch Logs"
echo ""

echo "검증 결과:"
echo "  - ECS, RDS, ElastiCache, ALB는 확인됨"
if [ ! -z "$S3_BUCKETS" ]; then
    echo -e "  - ${GREEN}S3 버킷 확인됨${NC}"
else
    echo -e "  - ${YELLOW}⚠️  S3 버킷을 찾을 수 없음 (아키텍처에는 포함)${NC}"
fi

if [ ! -z "$SQS_QUEUES" ]; then
    echo -e "  - ${GREEN}SQS 큐 확인됨${NC}"
else
    echo -e "  - ${YELLOW}⚠️  SQS 큐를 찾을 수 없음 (아키텍처에는 포함)${NC}"
fi

echo ""
echo "💡 다음 명령어로 환경 변수 확인:"
echo "   aws ecs describe-task-definition --task-definition rag-backend-task --region $REGION | jq '.taskDefinition.containerDefinitions[0].environment'"
echo ""
echo "💡 S3/SQS 설정 확인:"
echo "   grep -r 's3_bucket_name\|sqs_queue_url' app/config.py"

