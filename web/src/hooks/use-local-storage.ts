import { useCallback, useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

export function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => {
    if (typeof window === "undefined") {
      return initialValue;
    }

    const raw = window.localStorage.getItem(key);
    if (!raw) {
      return initialValue;
    }

    try {
      return JSON.parse(raw) as T;
    } catch {
      return initialValue;
    }
  });

  const setStoredValue = useCallback<Dispatch<SetStateAction<T>>>(
    (nextValue) => {
      setValue((currentValue) => {
        const resolvedValue =
          typeof nextValue === "function"
            ? (nextValue as (value: T) => T)(currentValue)
            : nextValue;

        if (typeof window !== "undefined") {
          try {
            window.localStorage.setItem(key, JSON.stringify(resolvedValue));
          } catch {
            // Ignore storage quota / serialization issues and keep in-memory state.
          }
        }

        return resolvedValue;
      });
    },
    [key],
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Ignore write failures; the hook should still behave like regular state.
    }
  }, [key, value]);

  return [value, setStoredValue] as const;
}
