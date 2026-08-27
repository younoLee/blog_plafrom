import { Link } from 'react-router-dom'
import type { PostSummary } from '../types/post'
import { IconLock } from './icons'

/**
 * 목록의 글 한 줄.
 *
 * **왜 컴포넌트로 뽑았나 (2026-08-18)** — 계정별 블로그(`/@handle`)가 생기면서 같은
 * 목록을 그리는 화면이 둘이 됐다(전체 모아보기 `/blog`, 개인 블로그 `/@handle`).
 * 마크업을 복사하면 `data-skin` 손잡이가 두 벌로 갈라지고, 그건 스킨이 한쪽 화면에서만
 * 먹는다는 뜻이다. 스킨과 화면 사이의 계약은 한 곳에만 있어야 한다.
 *
 * `data-skin` 이름은 index.css 주석의 목록과 짝이다. 여기서 이름을 바꾸면 이미 저장된
 * 사용자 스킨이 깨진다 — 클래스는 마음대로 바꿔도 되지만 이 속성은 계약이다.
 *
 * **삭제 확인창이 왜 이 파일에 있나 (2026-08-27)** — 호출부는 둘인데(HomePage,
 * AuthorPage) 둘 다 확인 없이 바로 지우고 있었다. 소프트 삭제가 아니고 되돌리는 UI도
 * 없으므로 '수정' 바로 옆의 오터치 한 번이 영구 삭제였다. 되돌릴 수 있는 동작들
 * (구독 취소·Pro 해지·초대 취소·계정 삭제)에는 이미 확인창이 있어서 규칙이 뒤집혀
 * 있었다. 확인을 호출부에 두면 세 번째 목록 화면이 생길 때 또 빠지므로, 버튼과 같은
 * 자리에 둔다. 마크업 계약을 한 곳에 모은 것과 같은 이유다.
 */
export function PostRow({
  post,
  canEdit,
  onDelete,
  basePath = '/blog',
}: {
  post: PostSummary
  /** 수정·삭제 버튼을 보일지. 본인 글이거나 관리자일 때 참. */
  canEdit: boolean
  onDelete: (id: number) => void
  /**
   * 태그·연재 칩이 돌아갈 목록 주소. 기본은 전체 모아보기.
   *
   * **왜 필요한가 (2026-08-27)** — `/@handle` 에서 태그를 누르면 `/blog?tag=` 로
   * 나가서 **그 사람의 블로그를 떠났다.** 누른 사람은 좁히려고 눌렀는데 넓어진다.
   * 칩이 어디로 갈지는 지금 어느 목록을 보고 있느냐에 달렸으므로 화면이 알려준다.
   */
  basePath?: string
}) {
  return (
    <article
      data-skin="post-card"
      className={`grid gap-x-6 py-6 ${post.cover_image ? 'sm:grid-cols-[1fr_10rem]' : 'grid-cols-1'}`}
    >
      {/* 커버가 있을 때만 그린다. 없으면 **아무것도 안 그린다** — 예전엔 편 번호를
          큰 상자에 얹어 자리를 채웠는데, 채울 것이 없는데 자리를 채우면 그게 곧
          빈 상자다. 목록에서는 제목이 그 자리를 대신한다. */}
      {post.cover_image && (
        <Link
          data-skin="post-thumb"
          to={`/blog/posts/${post.id}`}
          className="order-first mb-3 block overflow-hidden rounded-field sm:order-none sm:col-start-2 sm:row-start-1 sm:row-end-[-1] sm:mb-0 sm:self-start"
        >
          <img src={post.cover_image} alt="" loading="lazy" className="aspect-[16/9] w-full object-cover" />
        </Link>
      )}
      <h3 data-skin="post-title" className="flex items-center gap-2 text-xl font-semibold tracking-tight">
        <Link to={`/blog/posts/${post.id}`} className="transition hover:text-accent">{post.title}</Link>
        {post.visibility === 'private' && (
          <span className="inline-flex items-center gap-1 rounded-btn bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500 dark:bg-white/10 dark:text-gray-400">
            <IconLock className="h-3 w-3" />비공개
          </span>
        )}
        {post.visibility === 'subscribers' && (
          <span className="inline-flex items-center gap-1 rounded-btn bg-blue-50 px-2 py-0.5 text-xs font-medium text-accent">
            구독자공개
          </span>
        )}
      </h3>
      {/* 연재 뱃지 (2026-08-27). series 는 DB 컬럼에 인덱스까지 있고 이전/다음 편 API도
          있는데, 여태 **그 연재의 글 하나를 이미 우연히 연 사람에게만** 보였다.
          1편부터 읽고 싶은 방문자에게는 입구가 아예 없었다. */}
      {post.series && (
        <div data-skin="post-series" className="mt-2">
          <Link
            to={`${basePath}?series=${encodeURIComponent(post.series)}`}
            className="inline-flex items-center gap-1 rounded-btn bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent transition hover:bg-accent/20"
          >
            연재 · {post.series}
          </Link>
        </div>
      )}
      <Link
        data-skin="post-excerpt"
        to={`/blog/posts/${post.id}`}
        className="mt-2 block text-gray-500 transition hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
      >
        <p className="line-clamp-2 leading-relaxed">{post.excerpt}</p>
      </Link>
      {post.tags.length > 0 && (
        <div data-skin="post-tags" className="mt-3 flex flex-wrap gap-1.5">
          {post.tags.slice(0, 4).map((t) => (
            <Link
              key={t}
              to={`${basePath}?tag=${encodeURIComponent(t)}`}
              className="rounded-btn bg-black/[0.05] px-2 py-0.5 text-xs text-gray-600 transition hover:bg-accent/10 hover:text-accent dark:bg-white/10 dark:text-gray-300"
            >
              #{t}
            </Link>
          ))}
        </div>
      )}
      <div data-skin="post-meta" className="mt-3 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
          {/* 글쓴이 (2026-08-27). 예전엔 응답에 owner_id 숫자뿐이라 **다중 글쓴이
              플랫폼인데 목록에 누가 쓴 글인지 표시할 수가 없었다.**
              handle 이 있을 때만 링크다 — 서버가 공개 블로그를 가질 수 있는 역할에만
              handle 을 채우므로(schemas/post.py), 없으면 그 사람의 `/@handle` 은
              빈 목록이고 링크는 빈 페이지로 보내는 셈이 된다. */}
          {post.author_name && (
            <>
              {post.author_handle ? (
                <Link
                  to={`/${post.author_handle}`}
                  className="font-medium transition hover:text-accent"
                >
                  {post.author_name}
                </Link>
              ) : (
                <span className="font-medium">{post.author_name}</span>
              )}
              <span aria-hidden="true">·</span>
            </>
          )}
          <time>
            {new Date(post.created_at).toLocaleDateString()} · {post.reading_minutes}분 읽기
          </time>
        </div>
        {canEdit && (
          <div className="flex gap-3 text-sm">
            <Link to={`/blog/posts/${post.id}/edit`} className="text-accent hover:underline">수정</Link>
            <button
              type="button"
              onClick={() => {
                if (!window.confirm(`‘${post.title}’ 글을 정말 삭제할까?\n댓글까지 같이 지워지고 되돌릴 수 없어.`)) return
                onDelete(post.id)
              }}
              className="text-red-500 hover:underline"
            >
              삭제
            </button>
          </div>
        )}
      </div>
    </article>
  )
}
