# Insta_deunni — 임신 기록 릴스 제작 키트

레퍼런스 릴스 3편의 편집 문법을 분석해, **촬영본만 넣으면 같은 톤의 릴스(1080×1920, 30fps)가 자동 렌더링**되도록 만든 템플릿입니다.

## 1. 레퍼런스 분석 요약

| 구분 | Ref 1 (hi.poteau) | Ref 2 (asdfghjk0528) | Ref 3 (_dear.lua_) |
|---|---|---|---|
| 주제 | 임신 사실을 뒤늦게 안 스토리 | 6~10주 입덧 음식 기록 | 8주 젤리곰 초음파 |
| 길이 | 35초 | 113초 | 23초 |
| 구조 | 후킹 → 과거 회상 → 반전(두 줄) → 병원 → 초음파 감성 엔딩 | 음식 사진 나열 + 한 줄 코멘트 | 병원 가는 POV → 초음파 → 수치(1.77cm·170bpm) → 다짐 |
| 자막 | 상단 노란 하이라이트 후킹 + 하단 작은 흰 자막, 반전 컷 대형 텍스트 | 사진 중앙 핑크 자막 | 핑크 글자+흰 외곽선 |
| 컷 편집 | 1.5~2.5초 하드컷, 폰 촬영 원본 | 컷당 약 3~4초 | 영상 위주, 컷 길게 |

**공통 성공 공식:** ① 첫 1~3초 후킹 문구 ② 캡션은 1인칭 고백·질문형("혹시 저처럼…") ③ 초음파 컷으로 감성 마무리 ④ 해시태그 `#임신기록 #예비맘 #초기임산부`
> 위 수치는 각 게시물 임베드 데이터 기준이며, 조회수·도달 등 성과 지표는 확인하지 못했습니다(추가 확인 필요).

## 2. 사용법

```bash
# 1) projects/내프로젝트/ 폴더에 사진·영상을 넣고 project.json 작성 (sample 참고)
# 2) 렌더링
python3 make_reel.py projects/sample/project.json            # 최종본
python3 make_reel.py projects/sample/project.json --preview  # 빠른 확인
```

### project.json 항목
| 키 | 설명 |
|---|---|
| `style` | `vlog`(Ref 1 톤) / `cute`(Ref 3 핑크 톤) |
| `hook` | `top`(노란 박스 문구), `main`(큰 후킹 문구), `start`/`end`(초) |
| `clips[]` | `src`(사진/영상 경로), `dur`(초), `start`(영상 시작점), `speed`, `zoom`(사진 줌 강도) |
| `clips[].caption` | 하단 자막 |
| `clips[].emphasis` | 화면 중앙 대형 강조 문구 (예: "두줄?!?!") |
| `clips[].ending` | 엔딩 감성 문구 (예: "잘 지내보자") |
| `bgm` | `{"src": "bgm.mp3", "start": 0, "volume": 0.8}` — 없으면 무음. **인스타 업로드 시 앱 내 음원 추가 권장**(저작권) |

## 3. 샘플
`projects/sample/sample_reel.mp4` — 촬영 가이드 카드(플레이스홀더)로 만든 24.6초 데모. 각 카드의 컷 설명대로 촬영해 같은 파일명으로 교체하면 됩니다.

폰트: Pretendard (SIL OFL 1.1)

## 4. 프로젝트: 임테기 두 줄 남편 서프라이즈 (`projects/surprise`)
- 결과물: `projects/surprise/surprise_reel.mp4` (28초)
- `media/01_test.jpg` 실사진 적용 / `placeholders/03~07, 10, 11.jpg` 는 남편 리액션 촬영본으로 교체 필요 (영상 파일이면 `src` 확장자만 `.mp4`로 변경)
- 자막에는 이모지 미사용(렌더링 폰트 미지원) → 이모지는 인스타 본문 캡션에 사용
- (업데이트) 남편 리액션 원본(`media/husband_raw.MOV`, 116초 가로 영상)을 세로 크롭해 적용. 원본은 용량(167MB) 문제로 git 제외 — 구글 드라이브 'Raw' 폴더 보관본 사용
- 컷별 `crop_x`(가로 영상 세로 크롭 중심), `volume`/`mute`(원본 음성) 옵션 추가, 최종 음량 -16 LUFS 정규화

## 5. 얼굴 블러 (`blur_faces.py`)
- project.json 에 `"blur_faces": {"model": "assets/models/yunet.onnx", "score": 0.5}` 추가 시 자막 입히기 **전** 단계에서 얼굴 자동 블러(모자이크+가우시안)
- 사진 컷은 자동 제외(곰 캔들 오검출 방지), 컷 단위 제외는 `"no_blur": true`
- 놓친 구간 수동 지정: `"manual": [{"start": 12.0, "end": 13.5, "box": [x, y, w, h]}]` (1080x1920 기준, 블러 전 합본 타임라인 기준 초)
- 필요 패키지: `pip install opencv-python-headless numpy` / 모델: OpenCV Zoo YuNet (MIT)

## 6. 프로젝트: 임테기 순서 (`projects/test_order`)
- 결과물: `projects/test_order/test_order_reel.mp4` (55.8초, 여성 AI 나레이션 포함 — BGM은 인스타 앱 내 음원 추가 권장)
- 구조: 후킹("임테기도 순서가 있다고?!") → STEP 1 얼리 → STEP 2 원포 → 역전 → STEP 3 파이널 → 감성 엔딩
- 신규 옵션: `style: "box"`(반투명 박스 자막), 컷별 `label`(상단 STEP 라벨), `fit`(블러 배경으로 전체 표시), `z0`/`focus`(클로즈업 시작 배율·줌 중심), `emphasis_y`(강조 문구 세로 위치)
- (업데이트) 나레이션: project.json `narration`(voice/rate) + 컷별 `narration` 문구 → edge-tts(`ko-KR-SunHiNeural`)로 생성, 앞뒤 무음 제거 후 컷 길이를 낭독 길이에 자동 맞춤. 생성 파일은 `narration/`에 캐시 (`pip install edge-tts`)
- (업데이트) 컷별 `arrows: [{"x":, "y":, "delay":}]` — 원본 사진 픽셀 좌표(화살표 촉 위치)를 주면 줌을 따라가는 노란 바운스 화살표 표시. `caption_y`로 자막 위치 개별 지정
