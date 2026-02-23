#!/bin/bash
# 펌웨어 1.0.2 업로드 스크립트

SERVER_URL=${OTA_SERVER_URL:-http://localhost:8080}

echo "펌웨어 업로드 중: 1.0.2"
echo "서버: ${SERVER_URL}"

curl -X POST "${SERVER_URL}/api/v1/admin/firmware" \
  -F "file=@/home/gihoon/OTA/OTA_GH/firmware_files/app_1.0.2.tar.gz" \
  -F "version=1.0.2" \
  -F "release_notes=Release 1.0.2"

echo ""
echo "업로드 완료"
