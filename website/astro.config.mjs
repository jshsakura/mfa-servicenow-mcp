// @ts-check
import mdx from "@astrojs/mdx";
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://jshsakura.github.io",
  base: "/mfa-servicenow-mcp",
  integrations: [
    starlight({
      title: "MFA ServiceNow MCP",
      description:
        "MFA-first ServiceNow MCP server for LLMs (Claude, OpenAI, etc.)",
      defaultLocale: "root",
      locales: {
        root: { label: "English", lang: "en" },
        ko: { label: "한국어", lang: "ko" },
        ja: { label: "日本語", lang: "ja" },
        hi: { label: "हिन्दी", lang: "hi" },
        zh: { label: "简体中文", lang: "zh-CN" },
        es: { label: "Español", lang: "es" },
      },
      logo: {
        src: "./src/assets/favicon.svg",
        replacesTitle: false,
      },
      favicon: "/favicon.png",
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/jshsakura/mfa-servicenow-mcp",
        },
      ],
      editLink: {
        baseUrl: "https://github.com/jshsakura/mfa-servicenow-mcp/edit/main/docs/",
      },
      customCss: ["./src/styles/custom.css"],
      head: [
        {
          tag: "link",
          attrs: {
            rel: "preconnect",
            href: "https://fonts.googleapis.com",
          },
        },
        {
          tag: "link",
          attrs: {
            rel: "stylesheet",
            href: "https://fonts.googleapis.com/css2?family=Gugi&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap",
          },
        },
        {
          tag: "link",
          attrs: {
            rel: "stylesheet",
            href: "https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css",
          },
        },
      ],
      sidebar: [
        {
          label: "Getting Started",
          translations: {
            ko: "시작하기",
            ja: "はじめに",
            hi: "शुरू करें",
            "zh-CN": "快速开始",
            es: "Primeros pasos",
          },
          items: [
            {
              slug: "llm-setup",
              label: "AI-Assisted Setup",
              translations: {
                ko: "AI 자동 설치",
                ja: "AI支援セットアップ",
                hi: "AI-सहायक सेटअप",
                "zh-CN": "AI 辅助安装",
                es: "Instalación asistida por IA",
              },
            },
            {
              slug: "CLIENT_SETUP",
              label: "Client Setup",
              translations: {
                ko: "클라이언트 설정",
                ja: "クライアント設定",
                hi: "क्लाइंट सेटअप",
                "zh-CN": "客户端配置",
                es: "Configuración del cliente",
              },
            },
            {
              slug: "WINDOWS_INSTALL",
              label: "Windows Installation",
              translations: {
                ko: "윈도우 설치",
                ja: "Windowsインストール",
                hi: "विंडोज़ इंस्टॉलेशन",
                "zh-CN": "Windows 安装",
                es: "Instalación en Windows",
              },
            },
          ],
        },
        {
          label: "Features & Tools",
          translations: {
            ko: "기능 및 도구",
            ja: "機能とツール",
            hi: "सुविधाएँ और टूल",
            "zh-CN": "功能与工具",
            es: "Funciones y herramientas",
          },
          items: [
            {
              slug: "TOOL_INVENTORY",
              label: "Tool Inventory",
              translations: {
                ko: "도구 인벤토리",
                ja: "ツール一覧",
                hi: "टूल सूची",
                "zh-CN": "工具清单",
                es: "Inventario de herramientas",
              },
            },
            {
              slug: "TOOL_PACKAGES",
              label: "Tool Packages (Advanced)",
              translations: {
                ko: "도구 패키지 (고급)",
                ja: "ツールパッケージ（上級）",
                hi: "टूल पैकेज (उन्नत)",
                "zh-CN": "工具包（高级）",
                es: "Paquetes de herramientas (avanzado)",
              },
            },
          ],
        },
        {
          label: "Guides",
          translations: {
            ko: "가이드",
            ja: "ガイド",
            hi: "गाइड",
            "zh-CN": "指南",
            es: "Guías",
          },
          items: [
            {
              slug: "catalog",
              label: "Service Catalog",
              translations: {
                ko: "서비스 카탈로그",
                ja: "サービスカタログ",
                hi: "सेवा कैटलॉग",
                "zh-CN": "服务目录",
                es: "Catálogo de servicios",
              },
            },
            {
              slug: "change_management",
              label: "Change Management",
              translations: {
                ko: "변경 관리",
                ja: "変更管理",
                hi: "परिवर्तन प्रबंधन",
                "zh-CN": "变更管理",
                es: "Gestión de cambios",
              },
            },
            {
              slug: "workflow_management",
              label: "Workflow & Flow Designer",
              translations: {
                ko: "워크플로우 및 플로우 디자이너",
                ja: "ワークフローとフローデザイナー",
                hi: "वर्कफ़्लो और फ़्लो डिज़ाइनर",
                "zh-CN": "工作流与 Flow Designer",
                es: "Flujos de trabajo y Flow Designer",
              },
            },
          ],
        },
      ],
    }),
    mdx(),
  ],
});
