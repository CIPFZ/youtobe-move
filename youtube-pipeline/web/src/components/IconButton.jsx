export function IconButton({ icon: Icon, children, ...props }) {
  return (
    <button {...props}>
      {Icon ? <Icon size={16} /> : null}
      <span>{children}</span>
    </button>
  );
}
