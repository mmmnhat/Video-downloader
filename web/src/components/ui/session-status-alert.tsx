import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

type SessionStatusAlertProps = {
  authenticated: boolean;
  notReadyTitle: string;
  message: string;
  connectedTitle?: string;
};

export function SessionStatusAlert({
  authenticated,
  notReadyTitle,
  message,
  connectedTitle = "Đã kết nối",
}: SessionStatusAlertProps) {
  return (
    <Alert>
      <AlertTitle>{authenticated ? connectedTitle : notReadyTitle}</AlertTitle>
      {!authenticated ? <AlertDescription className="text-xs">{message}</AlertDescription> : null}
    </Alert>
  );
}
