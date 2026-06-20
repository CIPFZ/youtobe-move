import { DashboardOutlined, DatabaseOutlined, PlayCircleOutlined, SearchOutlined, SettingOutlined, VideoCameraOutlined } from "@ant-design/icons";
import { Button, Layout, Menu, Space, Typography } from "antd";
import { NavLink, Outlet, useLocation } from "react-router-dom";

const { Header, Sider, Content } = Layout;

const navItems = [
  { key: "/dashboard", icon: <DashboardOutlined />, label: <NavLink to="/dashboard">总览</NavLink> },
  { key: "/videos", icon: <VideoCameraOutlined />, label: <NavLink to="/videos">视频队列</NavLink> },
  { key: "/discovery", icon: <SearchOutlined />, label: <NavLink to="/discovery">发现管理</NavLink> },
  { key: "/operations", icon: <PlayCircleOutlined />, label: <NavLink to="/operations">运行监控</NavLink> },
  { key: "/settings", icon: <SettingOutlined />, label: <NavLink to="/settings">系统设置</NavLink> },
];

export function AppLayout({ state, actions }) {
  const location = useLocation();
  const selectedKey = navItems.find((item) => location.pathname.startsWith(item.key))?.key || "/dashboard";

  return (
    <Layout className="app-shell">
      <Sider className="app-sider" width={224} breakpoint="lg" collapsedWidth={0}>
        <div className="brand">
          <DatabaseOutlined />
          <div>
            <Typography.Title level={4}>YouTube Pipeline</Typography.Title>
            <span>自动搬运工作台</span>
          </div>
        </div>
        <Menu className="side-menu" mode="inline" selectedKeys={[selectedKey]} items={navItems} />
      </Sider>
      <Layout>
        <Header className="app-header">
          <div>
            <Typography.Title level={3}>YouTube Pipeline</Typography.Title>
            <span className="muted">发现、下载、文案、发布队列</span>
          </div>
          <Space wrap>
            <Button onClick={actions.runWorker}>运行一轮</Button>
            <Button onClick={actions.discoverDryRun}>发现预览</Button>
            <Button type="primary" onClick={actions.refreshCurrentPage} loading={state.loading}>刷新</Button>
          </Space>
        </Header>
        <Content className="app-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
