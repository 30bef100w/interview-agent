"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import FeedbackModal from "@/components/FeedbackModal";

type FeedbackContextValue = {
  openContact: () => void;
};

const FeedbackContext = createContext<FeedbackContextValue | null>(null);

export function useFeedback() {
  const ctx = useContext(FeedbackContext);
  if (!ctx) {
    throw new Error("useFeedback must be used within FeedbackProvider");
  }
  return ctx;
}

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [contactOpen, setContactOpen] = useState(false);

  const openContact = useCallback(() => setContactOpen(true), []);

  const value = useMemo(() => ({ openContact }), [openContact]);

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <FeedbackModal mode="contact" open={contactOpen} onClose={() => setContactOpen(false)} />
    </FeedbackContext.Provider>
  );
}
