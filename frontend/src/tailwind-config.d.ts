declare module '*/tailwind.config.js' {
  const config: import('tailwindcss').Config & { content: string[] };
  export default config;
}
