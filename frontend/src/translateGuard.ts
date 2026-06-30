// 브라우저 자동번역(구글 번역 / 디스코드·인스타 같은 인앱 브라우저의 번역)이 화면의
// 텍스트 노드를 <font>로 감싸면, React가 형제 노드를 옮길 때 removeChild/insertBefore가
// "이 노드는 이 부모의 자식이 아니다"라며 예외를 던져 앱이 통째로 크래시난다.
//   예) Failed to execute 'insertBefore' on 'Node': The node before which the new node
//       is to be inserted is not a child of this node.
// 번역기의 DOM 변형은 우리가 막을 수 없으므로, 이 두 메서드를 감싸 '부모가 아니면
// 조용히 건너뛰도록(no-op)' 만들어 앱 전체를 보호한다. 정상 경로(부모가 맞을 때)는
// 원본을 그대로 호출하니 동작 변화는 없고, 어긋난 경우만 크래시 대신 넘어간다.
// (React + 자동번역 충돌의 널리 쓰이는 표준 회피책.)
export function installTranslateGuard() {
  if (typeof Node !== 'function' || !Node.prototype) return

  const originalRemoveChild = Node.prototype.removeChild
  Node.prototype.removeChild = function (this: Node, child: Node) {
    if (child.parentNode !== this) {
      if (import.meta.env.DEV) console.warn('[translateGuard] removeChild 건너뜀(부모 불일치)', child)
      return child
    }
    return originalRemoveChild.call(this, child)
  } as typeof Node.prototype.removeChild

  const originalInsertBefore = Node.prototype.insertBefore
  Node.prototype.insertBefore = function (this: Node, newNode: Node, referenceNode: Node | null) {
    if (referenceNode && referenceNode.parentNode !== this) {
      if (import.meta.env.DEV) console.warn('[translateGuard] insertBefore 건너뜀(기준노드 부모 불일치)', referenceNode)
      return newNode
    }
    return originalInsertBefore.call(this, newNode, referenceNode)
  } as typeof Node.prototype.insertBefore
}
