import { Button } from "antd";

export function IconButton({ icon: Icon, children, className = "", ...props }) {
  const type = className.includes("primary") ? "primary" : "default";
  const danger = className.includes("danger");

  return (
    <Button {...props} type={type} danger={danger} icon={Icon ? <Icon size={16} /> : null}>
      {children}
    </Button>
  );
}
