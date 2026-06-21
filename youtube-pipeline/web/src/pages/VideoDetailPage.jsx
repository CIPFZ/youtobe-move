import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Button, Space, Typography } from "antd";
import { DetailSection } from "../sections/DetailSection";

const { Text } = Typography;

export function VideoDetailPage({ state, actions, rawActions, showToast }) {
  const { videoId } = useParams();
  const navigate = useNavigate();

  useEffect(() => {
    if (videoId && state.selectedId !== videoId) {
      rawActions.selectVideo(videoId).catch((error) => showToast(error.message));
    }
  }, [videoId]);

  return (
    <div className="page-stack">
      <div className="page-toolbar">
        <Button icon={<ArrowLeft size={16} />} onClick={() => navigate("/videos")}>
          返回队列
        </Button>
        <Space size={8}>
          <Text type="secondary">当前视频</Text>
          <Text code>{videoId}</Text>
        </Space>
      </div>
      <DetailSection state={state} actions={actions} showToast={showToast} />
    </div>
  );
}
