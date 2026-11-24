"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { usd } from "@/lib/format";

const PrivacyContext = createContext({
  hidden: true,
  toggle: () => {},
});

export function PrivacyProvider({ children }: { children: React.ReactNode }) {
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    setHidden(window.localStorage.getItem("sentinel-hide-values") !== "0");
  }, []);

  function toggle() {
    setHidden((current) => {
      const next = !current;
      window.localStorage.setItem("sentinel-hide-values", next ? "1" : "0");
      return next;
    });
  }

  return (
    <PrivacyContext.Provider value={{ hidden, toggle }}>
      {children}
    </PrivacyContext.Provider>
  );
}

export function usePrivacy() {
  return useContext(PrivacyContext);
}

export function Money({
  value,
  digits = 2,
}: {
  value: number | null | undefined;
  digits?: number;
}) {
  const { hidden } = usePrivacy();
  if (hidden) return <span className="num">••••</span>;
  return <span className="num">{usd(value, digits)}</span>;
}
