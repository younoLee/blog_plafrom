# 프론트엔드

이 블로그 플랫폼의 화면. 빌드 결과는 S3 정적 호스팅으로 올라가고 `/api/*`만 CloudFront가
EC2로 보낸다. 전체 구조와 배포는 저장소 루트의 [`README.md`](../README.md)를 본다.

2026-09-02까지 이 파일은 Vite 템플릿이 만들어준 원문 그대로였다. 이 프로젝트에 대해
아무것도 안 적혀 있었으므로 다시 썼다.

## 무엇으로 만들었나

React 19 · TypeScript · Vite · Tailwind CSS v4 · React Router. 마크다운 렌더는
react-markdown, 결제 화면은 토스페이먼츠 SDK를 쓴다. 정확한 버전은 `package.json`에 있다.

```
src/
  pages/        화면 (Home·PostDetail·Write·Admin·Status·Payment·Subscriptions 등)
  components/   화면 사이에서 재사용하는 조각
  api/          백엔드 호출 (http.ts가 토큰·에러 처리의 단일 통로)
  auth/         로그인 상태
  types/        API 응답 타입
scripts/gen-static.mjs   개발일지 아카이브·RSS·sitemap을 빌드 시점에 생성한다
```

## 돌리는 법

개발 서버만 따로 띄우려면 `npm ci && npm run dev` (http://localhost:5173).
백엔드까지 같이 필요하면 저장소 루트에서 `docker compose up -d --build`를 쓴다.

| 명령 | 하는 일 |
|---|---|
| `npm run dev` | 개발 서버 |
| `npm test` | vitest 1회 실행 |
| `npm run lint` | eslint |
| `npm run build` | `tsc -b` → `vite build` → `gen-static.mjs` |
| `npm run preview` | 빌드 결과 미리보기 |

`npm run build`는 셋을 이어서 돈다. 타입 오류가 있으면 첫 단계에서 멈추므로,
빌드가 실패했는데 vite 로그가 안 보이면 `tsc` 쪽을 먼저 본다.

## 이 기계에서 빌드가 EACCES로 죽는 함정

이 저장소를 docker로 돌린 적이 있어서 **root 소유 캐시 폴더**가 남아 있다. 증상이
권한 문제로 안 읽히고 "코드가 틀렸다"처럼 보이는 게 나쁘다.

| 폴더 | 죽는 명령 | 증상 |
|---|---|---|
| `node_modules/.tmp` | `tsc -b` (즉 `npm run build`) | `TS5033 ... EACCES` |
| `node_modules/.vite-temp` | `vitest` (즉 `npm test`) | `Startup Error: EACCES` |
| `node_modules/.vite` | vite 의존성 사전 번들 | 캐시 쓰기 실패 |
| `dist` | `vite build` | `vite:prepare-out-dir` 권한 거부 |

없애는 쪽이 낫다. 소유자가 root라 sudo가 필요하다.

```bash
sudo rm -rf node_modules/.tmp node_modules/.vite-temp node_modules/.vite dist
```

지울 수 없는 상황이면 캐시 경로를 밖으로 돌려서 우회한다. `tsc -b`는 프로젝트 참조를
쓰느라 빌드정보 파일 위치를 못 바꾸므로, tsconfig를 하나씩 `-p`로 돌린다.

```bash
npx tsc -p tsconfig.app.json --noEmit --tsBuildInfoFile /tmp/tsapp.tsbuildinfo
```

`dist`는 폴더 자체가 사용자 소유라 `mv`로 옆에 밀어두는 것만으로도 빌드가 지나간다.
CI에서는 매번 새 체크아웃이라 이 함정이 없다. 이 기계에서만 나온다.
