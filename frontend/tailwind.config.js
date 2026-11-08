/** RAGGuard design tokens. Exact values from the product design system; use these names, never raw hex, in components. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        app: "#F8FAFC", // application background
        workspace: "#FFFFFF", // workspace / card background
        sidebar: { DEFAULT: "#111827", hover: "#1F2937", active: "#312E81", text: "#9CA3AF", icon: "#C7D2FE" },
        surface: { DEFAULT: "#F1F5F9", hover: "#F8FAFC" }, // secondary surface / hover surface
        brand: { DEFAULT: "#4F46E5", hover: "#4338CA", light: "#EEF2FF" },
        ink: { DEFAULT: "#0F172A", 2: "#64748B", 3: "#94A3B8" }, // primary / secondary / muted text
        line: { DEFAULT: "#E2E8F0", strong: "#CBD5E1" },
        success: { DEFAULT: "#059669", bg: "#ECFDF5" },
        warning: { DEFAULT: "#D97706", bg: "#FFFBEB" },
        critical: { DEFAULT: "#DC2626", bg: "#FEF2F2" },
        info: { DEFAULT: "#2563EB", bg: "#EFF6FF" },
        night: { DEFAULT: "#0B1020", 2: "#111827", 3: "#1B2338" }, // landing page and sign-in: the dark brand surface
      },
      fontFamily: { sans: ['"Inter Variable"', "Inter", "ui-sans-serif", "system-ui", "sans-serif"], mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"] },
      fontSize: {
        page: ["24px", { lineHeight: "32px", fontWeight: "600" }],
        section: ["16px", { lineHeight: "24px", fontWeight: "600" }],
        card: ["14px", { lineHeight: "20px", fontWeight: "500" }],
        body: ["14px", { lineHeight: "20px", fontWeight: "400" }],
        support: ["12px", { lineHeight: "16px" }],
        kpi: ["30px", { lineHeight: "36px", fontWeight: "600" }],
        table: ["13px", { lineHeight: "20px" }],
      },
      borderRadius: { card: "10px", control: "7px" },
      boxShadow: { card: "0 1px 2px rgba(15,23,42,0.04)", pop: "0 8px 24px rgba(15,23,42,0.12)" },
      spacing: { sidebar: "250px", topbar: "64px" },
    },
  },
  plugins: [],
};
