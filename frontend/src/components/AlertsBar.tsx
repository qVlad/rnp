interface Alert {
  level: "info" | "warning" | "danger";
  code: string;
  message: string;
}

const colors: Record<string, string> = {
  info: "border-accent/40 bg-accent/10 text-accent",
  warning: "border-warn/40 bg-warn/10 text-warn",
  danger: "border-danger/40 bg-danger/10 text-danger",
};

export default function AlertsBar({ alerts }: { alerts: Alert[] }) {
  if (!alerts || alerts.length === 0) return null;
  return (
    <div className="flex flex-col gap-2 mb-4">
      {alerts.map((a) => (
        <div
          key={a.code}
          className={`px-4 py-2 rounded-md border text-sm ${colors[a.level] ?? colors.info}`}
        >
          <span className="font-medium">⚠ </span>
          {a.message}
        </div>
      ))}
    </div>
  );
}
