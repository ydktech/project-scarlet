# Project Scarlet

개인 AI 비서 제작 프로젝트. Cerebras 추론 엔진 위에 Qwen3-235B 모델을 올려서 돌리는 에이전트 시스템.

## 구조

```
scarlett/
  config.py      # 설정 상수
  llm.py         # Cerebras LLM 클라이언트 (스트리밍)
  agent.py       # 에이전트 루프 (도구 감지 → 실행 → 최종 응답)
  tools.py       # 도구 스키마 + 실행 (web_search, fetch_url, calculate, get_current_time)
  memory.py      # L3 메타데이터 (세션, 관계 단계)
  semantic.py    # mem0 시맨틱 메모리 (벡터 검색)
  prompt.py      # 시스템 프롬프트 로딩 + 모드/표정 감지
modules/         # 시스템 프롬프트 모듈 (.md)
server.py        # FastAPI 백엔드 (SSE 스트리밍, TTS)
static/          # 프론트엔드 (단일 HTML)
build.py         # 프롬프트 빌더 (modules/ → setting.txt)
```

## 주요 기능

- **에이전트 도구 호출** — 웹 검색 (Tavily), URL 읽기, 계산기, 시간 조회
- **3계층 메모리** — 세션 히스토리 / JSON 메타데이터 / 벡터 DB 시맨틱 메모리
- **실시간 SSE 스트리밍** — 토큰 단위 타자기 효과
- **TTS** — Fish Audio API로 음성 합성, 문장 단위 프리페치 재생
- **이중 인격 모드** — angel / psycho, 키워드 기반 자동 전환 + UI 반영

## 실행

```bash
cp .env.example .env
# .env에 API 키 입력

uv sync
uv run python build.py   # 시스템 프롬프트 빌드
uv run server.py          # localhost:8000
```

## 필요한 API 키

| 키 | 용도 | 발급처 |
|----|------|--------|
| `CEREBRAS_API_KEY` | LLM 추론 | [cerebras.ai](https://cerebras.ai) |
| `FISH_API_KEY` | TTS 음성 합성 | [fish.audio](https://fish.audio) |
| `TAVILY_API_KEY` | 웹 검색 도구 | [tavily.com](https://tavily.com) |
