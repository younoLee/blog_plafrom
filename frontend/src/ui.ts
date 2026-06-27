// 앱 전체에서 공유하는 스타일 토큰 (애플풍: 알약 버튼·애플 블루·은은한 그림자)
export const ui = {
  // 기본 버튼: 애플 블루 알약(pill)
  btnPrimary:
    'inline-flex items-center justify-center gap-1.5 rounded-full bg-[#0071e3] px-5 py-2.5 text-sm font-medium text-white transition hover:bg-[#0077ed] active:scale-[0.98] dark:bg-[#0a84ff] dark:hover:bg-[#3898ff]',
  // 보조 버튼: 연한 회색 알약
  btnGhost:
    'inline-flex items-center justify-center gap-1.5 rounded-full bg-black/[0.06] px-5 py-2.5 text-sm font-medium text-gray-800 transition hover:bg-black/[0.1] active:scale-[0.98] dark:bg-white/10 dark:text-gray-100 dark:hover:bg-white/20',
  input:
    'w-full rounded-xl border border-black/10 bg-white px-4 py-3 text-sm transition placeholder:text-gray-400 focus:border-[#0071e3] focus:outline-none focus:ring-4 focus:ring-[#0071e3]/15 dark:border-white/15 dark:bg-white/5 dark:text-gray-100 dark:placeholder:text-gray-500',
  // 드롭다운: input과 같은 톤. 기본 화살표를 숨기고(appearance-none) 오른쪽에 직접 그린 꺾쇠를 얹음.
  // 감싸는 요소를 relative로 두고 그 안에 select(이 클래스)+IconChevronDown(우측 absolute)을 배치.
  // 옵션 팝업/스크롤바 등 네이티브 UI 색은 index.css의 color-scheme가 테마에 맞춰 처리한다.
  select:
    'w-full cursor-pointer appearance-none rounded-xl border border-black/10 bg-white py-3 pl-4 pr-10 text-sm transition hover:border-black/20 focus:border-[#0071e3] focus:outline-none focus:ring-4 focus:ring-[#0071e3]/15 dark:border-white/15 dark:bg-[#1c1c1e] dark:text-gray-100 dark:hover:border-white/25',
  // 카드: 더 둥글게, 테두리 옅게, 그림자는 hover 때만 부드럽게 떠오름
  card:
    'rounded-2xl border border-black/[0.07] bg-white p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition hover:shadow-[0_8px_30px_rgba(0,0,0,0.08)] dark:border-white/10 dark:bg-white/[0.06]',
  // 그라데이션 글자(블루→퍼플→핑크, 천천히 흐름) — 강조하고 싶은 단어/제목에
  gradientText:
    'animate-gradient bg-gradient-to-r from-[#0071e3] via-[#7c3aed] to-[#ec4899] bg-clip-text text-transparent',
  // 히어로 뒤 은은한 색 번짐 — 부모를 relative로 두고 그 안에 배치
  glow:
    'pointer-events-none absolute inset-x-0 -top-16 -z-10 mx-auto h-56 max-w-xl rounded-full bg-gradient-to-tr from-[#0071e3]/20 via-purple-400/15 to-pink-400/15 blur-3xl dark:from-[#0a84ff]/20',
}
