// A filed document: the aged-paper panel with an Oswald tab header. Used by the
// Record audit and the History archive.
export default function EvidenceDoc({ tabLeft, tabRight, width760 = false, className = '', style, children }) {
  return (
    <div className={`s-doc${width760 ? ' s-doc760' : ''} ${className}`.trim()} style={style}>
      <div className="dk-tab"><span>{tabLeft}</span><span>{tabRight}</span></div>
      {children}
    </div>
  )
}
