#!/bin/bash
# OTA 시스템 상태 확인 스크립트

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 설정
SERVER_URL=${OTA_SERVER_URL:-http://localhost:8080}
VEHICLE_ID=${1:-"vehicle_001"}

# 도움말
show_help() {
    cat << EOF
OTA 시스템 상태 확인 스크립트

사용법:
    $0 [vehicle_id]

인자:
    vehicle_id  - 확인할 차량 ID (기본: vehicle_001)

예시:
    $0
    $0 vehicle_002
    OTA_SERVER_URL=http://example.com:8080 $0 vehicle_001

EOF
}

if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    show_help
    exit 0
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}OTA 시스템 상태 확인${NC}"
echo -e "${BLUE}========================================${NC}"
echo "서버: ${SERVER_URL}"
echo "차량: ${VEHICLE_ID}"
echo ""

# 1. 서버 헬스체크
echo -e "${YELLOW}[1] 서버 상태 확인${NC}"
if curl -s "${SERVER_URL}/health" > /dev/null 2>&1; then
    HEALTH=$(curl -s "${SERVER_URL}/health")
    echo -e "${GREEN}✓ 서버 정상${NC}"
    echo "${HEALTH}" | python3 -m json.tool 2>/dev/null || echo "${HEALTH}"
else
    echo -e "${RED}✗ 서버 연결 실패${NC}"
    exit 1
fi
echo ""

# 2. 차량 목록
echo -e "${YELLOW}[2] 등록된 차량 목록${NC}"
VEHICLES=$(curl -s "${SERVER_URL}/api/v1/vehicles")
echo "${VEHICLES}" | python3 -m json.tool 2>/dev/null || echo "${VEHICLES}"
echo ""

# 3. 특정 차량 정보
echo -e "${YELLOW}[3] 차량 상세 정보 (${VEHICLE_ID})${NC}"
VEHICLE_INFO=$(curl -s "${SERVER_URL}/api/v1/vehicles/${VEHICLE_ID}")
if echo "${VEHICLE_INFO}" | grep -q "error"; then
    echo -e "${RED}✗ 차량을 찾을 수 없습니다${NC}"
else
    echo -e "${GREEN}✓ 차량 정보:${NC}"
    echo "${VEHICLE_INFO}" | python3 -m json.tool 2>/dev/null || echo "${VEHICLE_INFO}"
fi
echo ""

# 4. 펌웨어 목록
echo -e "${YELLOW}[4] 사용 가능한 펌웨어${NC}"
FIRMWARE=$(curl -s "${SERVER_URL}/api/v1/firmware?active_only=true")
echo "${FIRMWARE}" | python3 -m json.tool 2>/dev/null || echo "${FIRMWARE}"
echo ""

# 5. 업데이트 확인 (차량 입장)
echo -e "${YELLOW}[5] 업데이트 확인 테스트${NC}"
# 현재 버전 추출
CURRENT_VERSION=$(echo "${VEHICLE_INFO}" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('vehicle', {}).get('current_version', '1.0.0'))" 2>/dev/null || echo "1.0.0")
echo "현재 버전: ${CURRENT_VERSION}"

UPDATE_CHECK=$(curl -s "${SERVER_URL}/api/v1/update-check?vehicle_id=${VEHICLE_ID}&current_version=${CURRENT_VERSION}")
echo "${UPDATE_CHECK}" | python3 -m json.tool 2>/dev/null || echo "${UPDATE_CHECK}"

UPDATE_AVAILABLE=$(echo "${UPDATE_CHECK}" | python3 -c "import sys, json; print(str(json.load(sys.stdin).get('update_available', False)).lower())" 2>/dev/null || echo "false")
if [ "${UPDATE_AVAILABLE}" = "true" ]; then
    echo -e "${GREEN}✓ 업데이트 가능!${NC}"
else
    echo -e "${BLUE}i 최신 버전입니다${NC}"
fi
echo ""

# 6. Docker 컨테이너 상태 (선택)
echo -e "${YELLOW}[6] Docker 컨테이너 상태${NC}"
if command -v docker &> /dev/null; then
    docker ps --filter "name=ota" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "Docker 컨테이너 정보 없음"
else
    echo "Docker가 설치되어 있지 않습니다"
fi
echo ""

# 7. MQTT 브로커 확인 (선택)
echo -e "${YELLOW}[7] MQTT 브로커 확인${NC}"
MQTT_HOST=${MQTT_BROKER_HOST:-localhost}
MQTT_PORT=${MQTT_BROKER_PORT:-1883}

if command -v nc &> /dev/null; then
    if nc -zv ${MQTT_HOST} ${MQTT_PORT} 2>&1 | grep -q succeeded; then
        echo -e "${GREEN}✓ MQTT 브로커 연결 가능 (${MQTT_HOST}:${MQTT_PORT})${NC}"
    else
        echo -e "${RED}✗ MQTT 브로커 연결 실패 (${MQTT_HOST}:${MQTT_PORT})${NC}"
    fi
elif command -v telnet &> /dev/null; then
    if timeout 2 telnet ${MQTT_HOST} ${MQTT_PORT} 2>&1 | grep -q Connected; then
        echo -e "${GREEN}✓ MQTT 브로커 연결 가능 (${MQTT_HOST}:${MQTT_PORT})${NC}"
    else
        echo -e "${RED}✗ MQTT 브로커 연결 실패 (${MQTT_HOST}:${MQTT_PORT})${NC}"
    fi
else
    echo "nc 또는 telnet이 필요합니다"
fi
echo ""

# 요약
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}상태 확인 완료${NC}"
echo -e "${BLUE}========================================${NC}"

# 업데이트 트리거 명령어 제안
if [ "${UPDATE_AVAILABLE}" = "true" ]; then
    LATEST_VERSION=$(echo "${UPDATE_CHECK}" | python3 -c "import sys, json; print(json.load(sys.stdin)['version'])" 2>/dev/null || echo "unknown")
    echo ""
    echo -e "${YELLOW}업데이트를 트리거하려면:${NC}"
    echo ""
    echo "curl -X POST ${SERVER_URL}/api/v1/admin/trigger-update \\"
    echo "  -H \"Content-Type: application/json\" \\"
    echo "  -d '{\"vehicle_id\": \"${VEHICLE_ID}\", \"version\": \"${LATEST_VERSION}\"}'"
    echo ""
fi
