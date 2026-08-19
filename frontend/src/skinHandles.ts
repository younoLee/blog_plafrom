/**
 * 스킨이 붙잡을 수 있는 자리의 **목록 하나**.
 *
 * 손잡이(`data-skin`)는 스킨과 화면 사이의 약속이다. 클래스는 우리가 화면을 손볼
 * 때마다 바뀌지만 이 이름들은 바뀌지 않기로 한 것이고, 그래서 남의 스킨이 안 깨진다.
 * 규칙과 이유는 `index.css`의 주석에 있다.
 *
 * **이 파일이 왜 따로 있나** — 목록이 세 군데에 살고 있었기 때문이다: 마크업(진짜),
 * index.css 주석(설명), 편집기 화면의 안내 문구(사람이 읽는 것). 08-19에 손잡이를
 * 열 개 늘리면서 셋이 갈라질 자리가 그만큼 늘었고, 갈라져도 **아무것도 안 깨진다** —
 * 안내에 없는 손잡이는 그냥 아무도 안 쓰고, 안내에만 있는 손잡이는 CSS를 써 놓고
 * "왜 안 먹지"에 갇힌다. 둘 다 조용한 고장이라 눈으로는 안 잡힌다.
 *
 * 그래서 화면 안내는 여기서 그리고, `skinHandles.test.ts`가 이 목록과 마크업과
 * index.css 주석 셋이 같은지 검사한다.
 */

export type HandleGroup = { group: string; names: string[] }

export const SKIN_HANDLES: HandleGroup[] = [
  { group: '틀', names: ['header', 'brand', 'nav', 'main', 'footer', 'layout'] },
  {
    group: '목록',
    names: [
      'hero',
      'post-grid',
      'post-card',
      'post-thumb',
      'post-title',
      'post-excerpt',
      'post-tags',
      'post-meta',
    ],
  },
  {
    group: '사이드바',
    names: ['sidebar', 'sidebar-profile', 'sidebar-recent', 'sidebar-tags'],
  },
  {
    group: '글 상세',
    names: [
      'article',
      'article-cover',
      'article-title',
      'article-meta',
      'article-tags',
      'article-body',
      'article-toc',
      'series',
      'related',
      'comments',
    ],
  },
  { group: '내 문장', names: ['slot-intro', 'slot-aside', 'slot-footer'] },
]

/** 평평한 이름 목록. 검사와 검색에 쓴다. */
export const SKIN_HANDLE_NAMES: string[] = SKIN_HANDLES.flatMap((g) => g.names)
