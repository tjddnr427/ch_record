# Phase 0 검증 기록

2026-10-15. 상태: PoC 구현 및 mock 검증 진행, 실장치 수용 검증 보류.

## 환경
실행 가능한 Python은 CPython 3.14.4 x64다. PRD 대상 Python 3.11은 확인되지 않았다. `py -0p`는 현재 환경에서 실행이 거부되었다. faster-whisper, CTranslate2, PyAudioWPatch가 설치되지 않았고 FFmpeg, ffprobe, nvidia-smi는 PATH에서 발견되지 않았다. GPU 조회도 권한 제한으로 실패하여 GPU 없음으로 단정하지 않는다.

환경 도구 출력: phase-0-environment.json. `python tools/check_environment.py`는 의도대로 blocked 및 종료 코드 1을 반환했다. `python tools/poc_capture.py --list-devices`도 미설치 오류를 반환했다. 오디오 캡처나 모델 다운로드는 실행하지 않았다.

## 구현 범위
- tools/check_environment.py: 버전·패키지·실행 파일 사전 검사. 하드웨어 검증을 대신하지 않는다.
- tools/poc_stt.py: 명시적 로컬 입력, 한국어 large-v3 GPU 우선, 명시적 CPU 옵션, 오프라인 캐시 기본, 원자적 JSON 저장.
- tools/poc_capture.py: PCM16 독립 트랙 스트리밍 기록, 프레임·시각 메타데이터, 무신호·장치 오류 처리.
- tools/check_sync.py: 1분 이상 WAV와 메타데이터 일관성 검사. 실제 발화 정렬·클럭 drift 측정은 별도다.

모델: GPT-5.4 mini 미제공으로 gpt-6-luna 서브 AI 세 개를 사용했다. 독립 코드 생성은 병렬 처리했고 통합, 인터페이스, 수정 지시 및 최종 검증은 메인 AI가 담당했다. 독립 리뷰는 docs/phase-0-review.md에 기록한다.

## 수용 검증
| 항목 | 상태 | 사유 |
|---|---|---|
| T01 10초 파일 실제 GPU 변환 | BLOCKED | 대상 Python·패키지·모델·GPU 런타임·실제 샘플 미확보 |
| T04/T05 실제 30초 2트랙 녹음 | BLOCKED | PyAudioWPatch·실제 장치 동작 미검증 |
| 1분 실제 트랙 정렬 검증 | BLOCKED | 실제 녹음 파일 미확보; 메타데이터 검사만 구현 |
| T08 장시간 drift | NOT_RUN | 단기 PoC로 대체하지 않음 |
| T11 실제 GPU DLL 및 CPU 대안 | BLOCKED | mock 오류 분류만 검증 |
| 패키지 버전 잠금 | NOT_RUN | 실장치 호환 검증 전 후보 목록만 제공 |

## 한계와 다음 단계
Python 3.11 x64와 후보 의존성, FFmpeg 및 GPU 런타임을 확보하고 한국어 샘플과 장치로 README의 실행 절차를 수행한다. 통과 후에만 호환 버전을 잠그고 Phase 1 진입 여부를 결정한다.

캡처 PoC는 일시정지·5분 분할·강제 종료 복구를 구현하지 않았다. STT PoC는 전체 파일 추론 및 결과 저장이므로 취소·세그먼트 복구·장시간 RAM 기준을 검증하지 않았다. 완성 제품으로 사용하지 않는다.

현재 폴더는 Git 저장소가 아니므로 커밋 및 git diff 검증은 수행하지 않았다. 기존 PRD는 수정하지 않았다.

## 최종 통합 검증
- `python -m unittest discover -s tests -v`: PASS, 29개. fake 모델·오디오 스트림과 합성 WAV 기반이며 실제 음성·장치 검증이 아님.
- `python -m compileall -q tools tests`: PASS.
- `python tools/check_environment.py`: BLOCKED, 종료 코드 1. 환경 문제를 의도대로 탐지함.
- `python tools/poc_stt.py --help`, `python tools/poc_capture.py --help`: PASS.
- 수정·회귀 검증: GPU DLL 분류, 빈 텍스트·겹치는 STT 시간, 잘린 WAV, 녹음 요청 길이 불일치, 트랙별 시작 추정 시각, 불완전 PCM 블록, manifest 저장 실패, 무음·장치 실패·자원 정리.
- 이 결과는 Phase 0 전체 통과 또는 Phase 1 진입 승인이 아님.
