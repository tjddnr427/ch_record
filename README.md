# Lecture STT — Phase 0

Windows 로컬 강의 STT의 GPU·오디오 캡처 PoC입니다. 제품 GUI는 아직 구현하지 않았습니다.
설계와 작업 규칙: AGENTS.md, docs/ENGINEERING.md, docs/tasks/phase-0.md.

## 개발 환경
PRD 대상은 Python 3.11 x64입니다. 프로젝트 가상환경에서 실행합니다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-poc.txt
.\.venv\Scripts\python.exe tools/check_environment.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

가상환경 활성화나 PowerShell 실행 정책 변경은 필요하지 않습니다.
FFmpeg/ffprobe 및 GPU 런타임은 별도 환경 검증이 필요합니다. 버전·성능·장치 호환성은 실제 PoC 후 확정합니다.

## 개인정보와 현재 범위
녹음·결과는 로컬 파일로 저장합니다. STT의 최초 모델 설치에는 네트워크가 필요할 수 있으며 명시적으로 허용해야 합니다. 캡처에는 참여자 고지·동의가 필요합니다.
PoC는 장치 검증용입니다. 긴 녹음의 분할·재시작 복구, 완성된 작업 큐·GUI·배포는 후속 단계입니다.

실행법과 검증 결과는 docs/phase-0-results.md에 기록합니다. mock 테스트 통과는 실제 GPU·오디오 장치 통과를 뜻하지 않습니다.

## Phase 0 실행 예시
다음 명령은 의존성 설치와 장치 확인 후 실행합니다. 파일 경로와 장치 ID는 실제 값으로 바꿉니다.

```powershell
# 한국어 음성이 있는 약 10초 샘플. 기본은 로컬 캐시만 사용.
.\.venv\Scripts\python.exe tools/poc_stt.py "sample.m4a" "result.json"
# 최초 모델 다운로드가 필요한 경우 위 명령에 --allow-download 추가.
# CPU 대안을 명시적으로 선택하려면 --device cpu 추가.

.\.venv\Scripts\python.exe tools/poc_capture.py --list-devices
.\.venv\Scripts\python.exe tools/poc_capture.py --loopback-id 1 --mic-id 2 --duration 30 --acknowledge-consent
# 1분 메타데이터 검증에는 --duration 60으로 별도 녹음.
.\.venv\Scripts\python.exe tools/check_sync.py "recordings/<session>/manifest.json"
```

`check_sync.py`의 사전 기본 허용치는 시작 시각 차이 100ms와 트랙 길이 차이 100ms입니다. 1024 프레임 블록과 워커 스케줄링 오차를 고려한 PoC 검사 기준이며 실장치 적합성은 미검증입니다. 이는 WAV·타이밍 메타데이터 검사이며 실제 발화의 음향 정렬이나 장시간 drift를 측정하지 않습니다. 동기화 성공 판정에는 동일 신호의 두 트랙 정렬 실측이 추가로 필요합니다.
