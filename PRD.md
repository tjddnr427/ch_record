# Lecture STT — 상세 제품 요구사항 정의서 (PRD v5)

> 2026-10-15 · 상태: Codex 구현 전 설계안 · 대상: Windows PC 로컬 앱

## 1. 제품 개요 및 결정사항

제품명: Lecture STT. Windows 10/11 x64 PC에서만 실행하는 오프라인 우선 개인용 음성 텍스트 변환 도구. 갤럭시 S24+ 녹음 파일 전송, 강의 영상 파일 불러오기, Windows 출력 소리 녹음, Discord/회의의 출력+마이크 동시 녹음 지원. 상시 서버·모바일 앱·웹 앱·로그인·유료 API는 구현하지 않는다. 사용자가 PC를 켜고 프로그램을 실행할 때만 처리한다. 최초 모델 설치에는 인터넷이 필요하다.

## 2. 문제와 성공 기준

1~2시간 이상 한국어 강의를 수기로 기록하기 어렵다. 사용자는 긴 음성을 로컬에서 정확히 텍스트화하고 TXT/SRT로 저장하고 싶다. 성공: 2시간 파일을 UI 응답 중단 없이 처리; 출력 장치 loopback과 마이크 동시 녹음; 예기치 않은 종료 후 기록 세그먼트 복구; TXT/SRT 저장; CPU fallback; 서버 없이 동작. 성능은 실측 전 보장하지 않는다. 초기 목표는 정확도 우선, 변환 속도는 벤치마크로 기록한다.

## 3. 사용자 시나리오

S1 갤럭시 녹음 앱에서 m4a 녹음→USB/Quick Share로 PC 전송→파일 드롭→한국어 변환→편집·저장. S2 PC에서 온라인 강의 재생→시스템 소리 녹음→중지→변환→타임스탬프 포함 저장. S3 Discord 회의→헤드폰 출력과 마이크 입력 각각 캡처→분리 트랙 보존→동기화 믹스→변환→TXT/SRT. S4 MP4/MKV 영상 파일을 직접 열어 오디오 추출 후 변환. 녹음 전 참석자 고지·동의 확인은 사용자 책임이며 앱에서 안내한다.

## 4. 기능 요구사항: 입력·녹음

FR-01 파일 선택/드래그앤드롭, 다중 파일 대기열, m4a/mp3/wav/flac/ogg/mp4/mkv; ffprobe로 메타데이터 확인. FR-02 WASAPI loopback 출력 장치 선택 및 레벨 표시; 선택 장치의 모든 소리 포함 가능, 앱별 분리는 미지원. FR-03 마이크 장치 선택, 별도 트랙 동시 캡처. FR-04 시작/일시정지/재개/중지; 5분 내외 분할 기록, 세그먼트 원자적 확정, 디스크 공간 경고. FR-05 장치 해제·헤드셋 전환·무음·독점 모드 문제 안내. FR-06 입력 신호가 없으면 조용히 빈 파일을 성공 처리하지 말 것.

## 5. 기능 요구사항: STT·출력

FR-07 faster-whisper large-v3, language=ko 기본, beam_size=5 기본, VAD는 선택 가능하고 세그먼트 타임스탬프 원본 기준으로 보정. FR-08 CUDA float16 우선; VRAM 부족 시 int8_float16 옵션 또는 사용자 확인 후 CPU int8. FR-09 작업 시작/취소/재시도/실패 사유 및 경과 시간; 실제 처리량 기반 진행률, 추정치와 확정치를 구분. FR-10 결과 세그먼트 타임코드·편집·검색. FR-11 UTF-8 TXT, SRT 저장, 선택적으로 JSON 내부 메타데이터. FR-12 취소 또는 장애 시 완료 세그먼트 복구. FR-13 오디오 원본 및 녹음 트랙 보존 정책과 정리 기능.

## 6. 비기능·제약

NFR-01 기본 데이터 로컬 보관, 외부 전송 금지. NFR-02 UI 이벤트 루프에서 무거운 작업 실행 금지; worker process 분리 권장. NFR-03 2시간 이상 녹음 시 RAM 선형 증가 금지, 스트리밍 디스크 기록. NFR-04 파일 경로 한글/공백/긴 경로 지원. NFR-05 로그에 오디오 원문·인식 문장·개인 경로를 기본 출력하지 않음. NFR-06 앱 종료 시 진행 작업 종료 확인 및 복구 정보 기록. NFR-07 Win10/11 x64 지원을 목표로 실제 장치별 검증. NFR-08 DRM 보호 콘텐츠 녹음 가능성 보장하지 않음.

## 7. 기술 스택과 선정 이유

Python 3.11 x64: 생태계와 GPU 패키지 호환성 기준. PySide6 Qt Widgets: Windows 네이티브 GUI, QThread/Signal; Qt Designer 선택. faster-whisper+CTranslate2: 로컬 Whisper 추론. NVIDIA 드라이버+CUDA 12 cuBLAS+cuDNN 9 런타임: 현재 CTranslate2 GPU 요구사항에 맞추되 실제 버전 호환 매트릭스 검증. PyAudioWPatch: Windows WASAPI loopback 후보, PoC 후 고정. FFmpeg/ffprobe: 영상 오디오 추출·믹싱·리샘플·검증(Whisper 입력 디코딩 자체는 PyAV로도 가능). SQLite: 로컬 작업 목록과 복구 메타데이터. pytest/pytest-qt: 자동 테스트. PyInstaller: Windows 배포 빌드, 라이선스 및 DLL 번들 검토. Git + VS Code + Codex: 개발.

## 8. 설치 프로그램·다운로드 출처

필수: Python 3.11 64-bit https://www.python.org/downloads/ ; Git https://git-scm.com/downloads ; VS Code https://code.visualstudio.com/ ; NVIDIA GPU 드라이버 https://www.nvidia.com/Download/index.aspx ; FFmpeg https://ffmpeg.org/download.html (Windows 빌드 링크 확인); CUDA Toolkit https://developer.nvidia.com/cuda-downloads ; cuDNN https://developer.nvidia.com/cudnn ; Codex는 공식 OpenAI 안내에 따라 VS Code 확장 또는 CLI 설치. 권장: Windows Terminal, 7-Zip. Python 패키지는 프로젝트 .venv 안에서 pip로 설치. CUDA Toolkit 전체 설치가 항상 필요한 것은 아니며 실제 추론에 필요한 런타임 DLL이 핵심이다.

## 9. Windows 설치·환경 검증 명령

PowerShell: py -3.11 --version; git --version; nvidia-smi; ffmpeg -version; ffprobe -version. 프로젝트 폴더에서 py -3.11 -m venv .venv; .\.venv\Scripts\python.exe -m pip install --upgrade pip; .\.venv\Scripts\python.exe -m pip install pyside6 faster-whisper PyAudioWPatch pytest pytest-qt pyinstaller. 설치 버전은 PoC 이후 lockfile로 고정. .venv 활성화가 막히면 실행 정책을 바꾸지 않고 .venv\Scripts\python.exe 직접 사용. GPU 확인: .venv\Scripts\python.exe -c "import ctranslate2; print(ctranslate2.get_supported_compute_types('cuda'))"; CUDA DLL 오류 시 버전/경로/드라이버 확인. 실제 10초 샘플 GPU 변환을 최종 검증으로 삼는다.

## 10. 아키텍처와 프로세스

UI(Pyside6)→Application Service→Job Queue(SQLite)→Worker Process(STT Engine)→Results Repository. Audio Capture Service→WASAPI output adapter + Mic adapter→Segment Writer→Sync/Mix Service→Job Queue. FFmpeg Service는 프로세스 실행을 argument array로 호출하고 shell=True 금지. Capture는 별도 worker thread/process로 UI와 격리. 작업 상태: queued/preparing/running/cancelling/completed/failed/interrupted. 파일 기록은 temp→fsync→rename, DB 상태와 파일 시스템 재조정. 앱 재시작 시 interrupted 작업 복구 선택.

## 11. 오디오 캡처 상세

WASAPI loopback은 출력 엔드포인트에서 재생되는 소리를 포착한다. Bluetooth 출력 변경과 기본 장치 변경은 자동 무손실 전환을 보장하지 않고 알림·재선택 처리. 시스템과 마이크는 독립 스트림/시계이므로 캡처 시작 monotonic timestamp와 프레임 카운터 저장, 시간 정렬 및 장시간 drift 검사. 원본을 48kHz PCM WAV/FLAC 세그먼트로 기록, STT 직전에 16kHz mono로 정규화. 믹스 시 클리핑 방지; 원본 두 트랙 보존. 일시정지 구간은 결과 타임라인에서 제외하는 정책을 기본으로 하고 메타데이터에 실제 시간 기록. 녹음 시작 전에 5초 시험 녹음 버튼 제공.

## 12. STT 정확도 정책

기본 한국어 강의: large-v3, ko, beam_size 5, temperature 0, 조건부 이전 텍스트 사용은 긴 침묵/반복 환각 검사 후 조정. VAD는 켜기/끄기 옵션 제공, 발화 누락을 방지하기 위해 원본 타임라인과 정렬 테스트. 30~60초 청크 처리 시 경계 겹침·중복 제거 정책 명시. 전문 용어 힌트는 initial_prompt로 선택적 제공, 보장하지 않음. 변환 후 구간별 confidence 유사 지표는 확정 정확도 점수처럼 표현하지 않음.

## 13. GUI 화면 명세

메인 탭: [파일 변환] [시스템 녹음] [회의 녹음] [작업 기록] [설정]. 파일 탭: 드롭존, 목록, 모델·언어·장치 설정, 시작·취소. 시스템 탭: 출력 장치, 레벨 미터, 테스트, 녹음 타이머, 일시정지·중지. 회의 탭: 출력/마이크 각각 장치 선택·레벨 미터, 동의 안내, 녹음. 결과 화면: 타임코드 세그먼트 테이블, 편집창, 찾기, 원본 재생 위치 이동(후속), TXT/SRT 내보내기. 설정: 모델 다운로드/캐시, 기본 폴더, GPU/CPU, 저장 용량/정리, 개인정보. 접근성: 키보드 포커스, 상태 텍스트, 색상 외 구분.

## 14. 데이터 구조·경로

%LOCALAPPDATA%\LectureSTT\config.json, jobs.sqlite3, logs\; %USERPROFILE%\Documents\LectureSTT\Recordings\, Transcripts\ 기본. jobs(id UUID, source_type, source_path, status, model, device, language, duration_ms, created_at, updated_at, error_code). segments(job_id, idx, start_ms, end_ms, text, edited_text). recordings(id, session_start, output_device_id, mic_device_id, segment_manifest_path, consent_ack_at). 파일 메타데이터와 결과는 사용자 삭제 가능. SQLite WAL과 마이그레이션 버전 적용.

## 15. 오류 및 보안·라이선스

오류 코드: E_GPU_DLL, E_GPU_OOM, E_MODEL_DOWNLOAD, E_AUDIO_DEVICE, E_AUDIO_SILENT, E_DISK_FULL, E_FFMPEG, E_INPUT_UNSUPPORTED, E_JOB_INTERRUPTED. 사용자에게 복구 가능한 조치 안내, 상세 기술 로그 분리. 경로 인젝션 방지, subprocess shell=False, 모델 다운로드 체크섬/신뢰 출처, 실행 파일 서명 선택. 오디오/텍스트 자동 업로드 없음. 회의 녹음은 관련 법령과 참여자 고지·동의 고려. FFmpeg, Qt/PySide6, CTranslate2, Whisper 모델 및 기타 라이브러리의 배포 라이선스·고지 파일 검토 필수.

## 16. 테스트 매트릭스와 수용 조건

T01 10초 m4a→TXT; T02 2시간 m4a 안정 처리; T03 MP4 오디오 추출; T04 출력 장치 loopback 녹음; T05 Discord 출력+마이크 별도 트랙; T06 헤드폰 연결 해제; T07 무음·독점모드 경고; T08 장시간 클럭 drift; T09 디스크 공간 부족; T10 앱 강제 종료 후 세그먼트 복구; T11 GPU DLL 누락 및 CPU 대안; T12 VRAM 부족; T13 한글/공백 경로; T14 중지·취소·재시도; T15 SRT 시간 순서; T16 네트워크 차단 후 모델 캐시 실행; T17 패키징 후 깨끗한 PC 설치; T18 보안 로그 점검. 통과 기준은 실제 샘플·장치 기록과 재현 절차를 첨부하고, GPU 처리 시간은 벤치마크 결과로 기재한다.

## 17. 개발 단계 및 Codex 인계

Phase 0 PoC: 10초 파일 GPU 변환, 30초 WASAPI loopback+마이크 캡처, 1분 동기화 검증; 이 결과로 패키지 버전 잠금. Phase 1 파일 STT/내보내기. Phase 2 시스템 녹음. Phase 3 회의 2트랙·복구. Phase 4 장시간 테스트·UI 다듬기. Phase 5 PyInstaller 배포 및 설치 가이드. Codex 지시: 모든 단계에서 테스트 작성·실행, 실패한 환경 의존 테스트는 명시적으로 보류, 실제 GPU/오디오 장치 성공을 가정하지 말 것. 커밋 단위로 작업하고 PRD 변경 시 변경 기록 갱신.

## 18. 범위 제외 및 추후 확장

이번 범위 제외: 모바일 네이티브 앱, 웹/서버, 클라우드 STT, 실시간 자막, 자동 요약, 화자 분리, 앱별 오디오 분리, Discord 봇, DRM 우회. 추후 검토: 특정 앱 오디오 캡처(Windows process loopback API 별도 PoC), 실시간 자막, 화자 분리, 용어 사전, 번역, 검색 인덱싱, 자동 챕터 분할.

## 19. 근거 및 확인 필요

원본 PRD: 사용자 제공 2026-10-15 문서. 이전 v4 설계: AUDIO_CAPTURE_SPEC/ARCHITECTURE/UX_SPEC. 공식 참고: https://github.com/SYSTRAN/faster-whisper ; https://doc.qt.io/qtforpython-6/gettingstarted.html ; https://ffmpeg.org/download.html . 확정 전 확인: 사용자 OS 빌드/드라이버/VRAM, 실제 CUDA·cuDNN DLL, PyAudioWPatch 장치 동작, FFmpeg 배포 라이선스, PyInstaller 실행파일 백신 오탐, 모델 캐시 용량. 기술 선택은 설계 제안이며 사용자 PC에서 아직 설치·검증하지 않았다.

