import React, { useState, useEffect } from 'react';
import { RefreshCw, Server, Wifi, WifiOff, Download, CheckCircle, XCircle, Clock, AlertCircle } from 'lucide-react';

const API_BASE_URL = import.meta.env.VITE_APP_API_URL;
// console.log("API_BASE_URL =", API_BASE_URL);

const REFRESH_INTERVAL = 5000; // 5초

const OTADashboard = () => {    // “OTADashboard라는 화면 컴포넌트”를 만드는 함수
  const [serverHealth, setServerHealth] = useState(null);
  const [vehicles, setVehicles] = useState([]);
  const [firmware, setFirmware] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(new Date());

  // 데이터 가져오기
  const fetchData = async () => {
    // console.log("API_BASE_URL (inside fetchData) =", API_BASE_URL);

    try {
      const [healthRes, vehiclesRes, firmwareRes] = await Promise.all([
        fetch(`${API_BASE_URL}/health`),
        fetch(`${API_BASE_URL}/api/v1/vehicles`),
        fetch(`${API_BASE_URL}/api/v1/firmware?active_only=true`)
      ]);

      const health = await healthRes.json();
      const vehiclesData = await vehiclesRes.json();
      const firmwareData = await firmwareRes.json();

      setServerHealth(health);
      setVehicles(vehiclesData.vehicles || []);
      setFirmware(firmwareData.firmware || []);
      setLastUpdate(new Date());
      setLoading(false);
    } catch (error) {
      console.error('데이터 가져오기 실패:', error);
      setLoading(false);
    }
  };

  // 초기 로드 및 주기적 갱신
  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, []);

  // 상태별 색상
  const getStatusColor = (status) => {
    const colors = {
      'completed': 'bg-green-100 text-green-800 border-green-200',
      'downloading': 'bg-blue-100 text-blue-800 border-blue-200',
      'verifying': 'bg-yellow-100 text-yellow-800 border-yellow-200',
      'installing': 'bg-purple-100 text-purple-800 border-purple-200',
      'failed': 'bg-red-100 text-red-800 border-red-200',
      'idle': 'bg-gray-100 text-gray-800 border-gray-200'
    };
    return colors[status] || colors['idle'];
  };

  // 상태별 아이콘
  const getStatusIcon = (status) => {
    const icons = {
      'completed': <CheckCircle className="w-4 h-4" />,
      'downloading': <Download className="w-4 h-4" />,
      'verifying': <AlertCircle className="w-4 h-4" />,
      'installing': <RefreshCw className="w-4 h-4 animate-spin" />,
      'failed': <XCircle className="w-4 h-4" />,
      'idle': <Clock className="w-4 h-4" />
    };
    return icons[status] || icons['idle'];
  };

  // 업데이트 트리거
  const triggerUpdate = async (vehicleId, version = null) => {
    try {
      const payload = { vehicle_id: vehicleId };
      if (version) payload.version = version;

      const response = await fetch(`${API_BASE_URL}/api/v1/admin/trigger-update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (response.ok) {
        alert(`업데이트 명령 전송 완료: ${vehicleId}`);
        fetchData();
      } else {
        alert('업데이트 명령 전송 실패');
      }
    } catch (error) {
      alert('오류: ' + error.message);
    }
  };

  // 시간 포맷
  const formatTime = (dateString) => {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleString('ko-KR');
  };

  // 상대 시간
  const getRelativeTime = (dateString) => {
    if (!dateString) return '-';
    const date = new Date(dateString);
    const seconds = Math.floor((new Date() - date) / 1000);
    
    if (seconds < 60) return `${seconds}초 전`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}분 전`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}시간 전`;
    return `${Math.floor(seconds / 86400)}일 전`;
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 헤더 */}
      <div className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Server className="w-8 h-8 text-blue-600" />
              <div>
                <h1 className="text-2xl font-bold text-gray-900">OTA 대시보드</h1>
                <p className="text-sm text-gray-500">Over-The-Air Update System</p>
              </div>
            </div>
            
            <div className="flex items-center gap-4">
              {/* 서버 상태 */}
              <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 rounded-lg">
                {serverHealth?.mqtt_connected ? (
                  <Wifi className="w-4 h-4 text-green-600" />
                ) : (
                  <WifiOff className="w-4 h-4 text-red-600" />
                )}
                <span className="text-sm font-medium">
                  {serverHealth?.mqtt_connected ? 'MQTT 연결됨' : 'MQTT 끊김'}
                </span>
              </div>
              
              {/* 새로고침 버튼 */}
              <button
                onClick={fetchData}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                새로고침
              </button>
            </div>
          </div>
          
          {/* 마지막 업데이트 시간 */}
          <div className="mt-2 text-xs text-gray-500">
            마지막 업데이트: {lastUpdate.toLocaleTimeString('ko-KR')}
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <RefreshCw className="w-8 h-8 text-blue-600 animate-spin" />
          </div>
        ) : (
          <div className="space-y-6">
            {/* 통계 카드 */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-white rounded-lg shadow p-6 border border-gray-200">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-600">전체 차량</p>
                    <p className="text-3xl font-bold text-gray-900 mt-1">{vehicles.length}</p>
                  </div>
                  <Server className="w-12 h-12 text-blue-600 opacity-20" />
                </div>
              </div>

              <div className="bg-white rounded-lg shadow p-6 border border-gray-200">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-600">활성 펌웨어</p>
                    <p className="text-3xl font-bold text-gray-900 mt-1">{firmware.length}</p>
                  </div>
                  <Download className="w-12 h-12 text-green-600 opacity-20" />
                </div>
              </div>

              <div className="bg-white rounded-lg shadow p-6 border border-gray-200">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-600">업데이트 중</p>
                    <p className="text-3xl font-bold text-gray-900 mt-1">
                      {vehicles.filter(v => ['downloading', 'verifying', 'installing'].includes(v.status)).length}
                    </p>
                  </div>
                  <RefreshCw className="w-12 h-12 text-purple-600 opacity-20" />
                </div>
              </div>
            </div>

            {/* 펌웨어 목록 */}
            <div className="bg-white rounded-lg shadow border border-gray-200">
              <div className="px-6 py-4 border-b border-gray-200">
                <h2 className="text-lg font-semibold text-gray-900">활성 펌웨어</h2>
              </div>
              <div className="divide-y divide-gray-200">
                {firmware.length === 0 ? (
                  <div className="px-6 py-8 text-center text-gray-500">
                    등록된 펌웨어가 없습니다
                  </div>
                ) : (
                  firmware.map((fw) => (
                    <div key={fw.id} className="px-6 py-4 hover:bg-gray-50">
                      <div className="flex items-center justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-3">
                            <span className="text-lg font-semibold text-gray-900">
                              v{fw.version}
                            </span>
                            <span className="px-2 py-1 text-xs font-medium bg-green-100 text-green-800 rounded">
                              활성
                            </span>
                          </div>
                          <p className="text-sm text-gray-600 mt-1">{fw.filename}</p>
                          <p className="text-xs text-gray-500 mt-1">
                            크기: {(fw.file_size / 1024).toFixed(1)} KB | 
                            SHA256: {fw.sha256.substring(0, 16)}...
                          </p>
                          {fw.release_notes && (
                            <p className="text-sm text-gray-700 mt-2">{fw.release_notes}</p>
                          )}
                        </div>
                        <div className="text-xs text-gray-500">
                          {formatTime(fw.created_at)}
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* 차량 목록 */}
            <div className="bg-white rounded-lg shadow border border-gray-200">
              <div className="px-6 py-4 border-b border-gray-200">
                <h2 className="text-lg font-semibold text-gray-900">차량 목록</h2>
              </div>
              <div className="divide-y divide-gray-200">
                {vehicles.length === 0 ? (
                  <div className="px-6 py-8 text-center text-gray-500">
                    등록된 차량이 없습니다
                  </div>
                ) : (
                  vehicles.map((vehicle) => (
                    <div key={vehicle.id} className="px-6 py-4 hover:bg-gray-50">
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-3">
                            <h3 className="text-lg font-semibold text-gray-900">
                              {vehicle.vehicle_id}
                            </h3>
                            <span className={`flex items-center gap-1 px-2 py-1 text-xs font-medium rounded border ${getStatusColor(vehicle.status)}`}>
                              {getStatusIcon(vehicle.status)}
                              {vehicle.status}
                            </span>
                          </div>
                          
                          <div className="mt-2 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                            <div>
                              <p className="text-gray-500">현재 버전</p>
                              <p className="font-medium text-gray-900">
                                {vehicle.current_version || '-'}
                              </p>
                            </div>
                            <div>
                              <p className="text-gray-500">마지막 접속</p>
                              <p className="font-medium text-gray-900">
                                {getRelativeTime(vehicle.last_seen)}
                              </p>
                            </div>
                            <div>
                              <p className="text-gray-500">등록일</p>
                              <p className="font-medium text-gray-900">
                                {formatTime(vehicle.created_at).split(' ')[0]}
                              </p>
                            </div>
                            <div>
                              <p className="text-gray-500">업데이트</p>
                              <p className="font-medium text-gray-900">
                                {formatTime(vehicle.updated_at).split(' ')[1]}
                              </p>
                            </div>
                          </div>

                          {/* 최근 업데이트 히스토리 */}
                          {vehicle.recent_updates && vehicle.recent_updates.length > 0 && (
                            <div className="mt-3 p-3 bg-gray-50 rounded border border-gray-200">
                              <p className="text-xs font-medium text-gray-700 mb-2">최근 업데이트</p>
                              <div className="space-y-1">
                                {vehicle.recent_updates.slice(0, 3).map((update, idx) => (
                                  <div key={idx} className="text-xs text-gray-600 flex items-center gap-2">
                                    <span className={`w-2 h-2 rounded-full ${
                                      update.status === 'completed' ? 'bg-green-500' :
                                      update.status === 'failed' ? 'bg-red-500' : 'bg-yellow-500'
                                    }`} />
                                    <span>{update.from_version || '?'} → {update.target_version}</span>
                                    <span className="text-gray-400">({update.status})</span>
                                    <span className="text-gray-400 ml-auto">{getRelativeTime(update.started_at)}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>

                        {/* 액션 버튼 */}
                        <div className="ml-4">
                          <button
                            onClick={() => triggerUpdate(vehicle.vehicle_id)}
                            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
                          >
                            업데이트
                          </button>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default OTADashboard;