// Service Worker 기본 설치 및 활성화 라이프사이클 엔진
self.addEventListener('install', function(e) {
  // 로컬 구동 상태이므로 캐싱 처리를 최소화하여 실시간 웹소켓 충돌을 방지합니다.
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  return self.clients.claim();
});

self.addEventListener('fetch', function(e) {
  // 실시간 사내 메신저 데이터 패킷 통과 (네트워크 우선 처리)
});