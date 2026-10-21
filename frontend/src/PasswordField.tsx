import { useId, useState, type KeyboardEvent } from "react";
import { Eye, EyeOff } from "lucide-react";

export function submitAccountForm(event: KeyboardEvent<HTMLFormElement>) {
  if (
    event.key === "Enter" &&
    (event.ctrlKey || event.metaKey) &&
    !event.nativeEvent.isComposing
  ) {
    event.preventDefault();
    event.currentTarget.requestSubmit();
  }
}

export default function PasswordField({
  label,
  value,
  onChange,
  autoComplete = "new-password",
  minimum = 8,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: "current-password" | "new-password";
  minimum?: number;
  disabled?: boolean;
}) {
  const id = useId(),
    [visible, setVisible] = useState(false);
  return (
    <div className="account-field">
      <label htmlFor={id}>{label}</label>
      <div className="password-field">
        <input
          id={id}
          name={label.toLowerCase().replaceAll(" ", "-")}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required
          minLength={minimum}
          maxLength={128}
          autoComplete={autoComplete}
          disabled={disabled}
        />
        <button
          type="button"
          className="icon-button"
          aria-label={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`}
          aria-pressed={visible}
          onClick={() => setVisible(!visible)}
          disabled={disabled}
        >
          {visible ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      </div>
    </div>
  );
}
