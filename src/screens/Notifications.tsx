import type { NotificationItem } from "../notifications/types";
import type { UseNotificationsResult } from "../notifications/useNotifications";
import { formatListTimestamp } from "../notifications/store";

interface Props {
  result: UseNotificationsResult;
  onNavigate: (screen: string, targetId?: string) => void;
}

const CATEGORY_LABEL: Record<string, string> = {
  "incoming-transfer": "Incoming transfer",
  "transfer-accepted": "Transfer accepted",
  "transfer-rejected": "Transfer rejected",
  "transfer-cancelled": "Transfer cancelled",
  "transfer-expired": "Transfer expired",
  "transaction-confirmed": "Confirmed",
  "transaction-pending": "Pending",
  "transaction-rejected": "Rejected",
  "processing-confirmed": "Processing confirmed",
};

export default function Notifications({ result, onNavigate }: Props) {
  const { notifications, unread, loading, error, markRead, markAllRead, clearAll } = result;

  function handleOpen(n: NotificationItem) {
    if (!n.read) markRead(n.id);
    if (n.targetScreen && n.targetId) {
      onNavigate(n.targetScreen, n.targetId);
    } else if (n.targetScreen) {
      onNavigate(n.targetScreen);
    }
  }

  return (
    <div className="screen">
      <h1>Notifications</h1>

      {error && <p className="status status-error">{error}</p>}
      {loading && notifications.length === 0 && <p className="status">Loading...</p>}

      {notifications.length > 0 && (
        <div className="notification-actions">
          <span className="notification-count">
            {unread > 0 ? `${unread} unread` : "All read"}
          </span>
          <div className="button-group">
            {unread > 0 && (
              <button className="button button-secondary button-small" onClick={markAllRead}>
                Mark all as read
              </button>
            )}
            <button className="button button-secondary button-small" onClick={clearAll}>
              Clear all
            </button>
          </div>
        </div>
      )}

      {notifications.length === 0 && !loading && !error && (
        <p className="empty-state">No notifications. You will see updates here when transfers, processing operations, or workflow state changes are confirmed on the chain.</p>
      )}

      {notifications.length > 0 && (
        <ul className="notification-list">
          {notifications.map((n) => (
            <li
              key={n.id}
              className={"notification-item" + (n.read ? "" : " notification-unread")}
              onClick={() => handleOpen(n)}
            >
              <div className="notification-header">
                <span className="notification-category">
                  {CATEGORY_LABEL[n.category] || n.category}
                </span>
                {!n.read && <span className="notification-dot" />}
                <span className="notification-time">{formatListTimestamp(n.createdAt)}</span>
              </div>
              <p className="notification-title">{n.title}</p>
              <p className="notification-detail">{n.detail}</p>
              {n.targetScreen && (
                <span className="notification-link">
                  {n.targetScreen === "transfers" && "Open transfers"}
                  {n.targetScreen === "processing" && "Open processing"}
                  {n.targetScreen === "traceability" && "View traceability"}
                  {n.targetScreen === "txstatus" && "View transaction status"}
                  {n.targetScreen === "batches" && "Open batches"}
                  {n.targetScreen === "materials" && "Open materials"}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
