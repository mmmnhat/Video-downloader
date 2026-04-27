import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

type SessionStatusAlertProps = {
  authenticated: boolean;
  notReadyTitle: string;
  message: string;
};

export function SessionStatusAlert({
  authenticated,
  notReadyTitle,
  message,
}: SessionStatusAlertProps) {
  if (authenticated) {
    return null;
  }
  
  return (
    <Alert>
      <AlertTitle>{notReadyTitle}</AlertTitle>
      <AlertDescription className="text-xs">{message}</AlertDescription>
    </Alert>
  );
}
