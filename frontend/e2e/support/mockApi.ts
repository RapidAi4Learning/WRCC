// Canned backend for the visual captures. Every `/api/*` request the browser
// makes is answered here, so the screens can be rendered in any state without
// a database, an LLM or a network login.
//
// The data is realistic on purpose — real WRCC course codes, real-length post
// bodies — because a layout that only ever sees "Lorem" hides its overflow bugs.

import type { Page, Route } from "@playwright/test";

const DAY_MS = 86_400_000;
// A fixed "now", mirrored in the browser with page.clock, so relative dates
// ("Expires in 5 days", "Crawled 15 min ago") read the same on every run and
// screenshots can be compared pixel for pixel.
export const FIXED_NOW = new Date("2026-09-10T09:00:00+10:00");
const NOW = FIXED_NOW.getTime();
const iso = (offsetDays = 0) => new Date(NOW + offsetDays * DAY_MS).toISOString();

const USER = {
  id: "user-1",
  email: "alex.smith@wrcc.nsw.edu.au",
  display_name: "Alex Smith",
};

const COURSES = [
  { code: "HLTAID011", title: "Provide First Aid", category: "First Aid", accredited: true },
  { code: "HLTAID009", title: "Provide Cardiopulmonary Resuscitation", category: "First Aid", accredited: true },
  { code: "SITHFAB021", title: "Provide Responsible Service of Alcohol", category: "Liquor and Gaming", accredited: true },
  { code: "CPCWHS1001", title: "Prepare to Work Safely in the Construction Industry", category: "Construction", accredited: true },
  { code: "BSB-EXCEL", title: "Microsoft Excel — Intermediate", category: "Business and IT", accredited: false },
  { code: "CHC-SIGN", title: "Auslan for Beginners", category: "Community", accredited: false },
].map((course, index) => ({
  id: `course-${index + 1}`,
  course_code: course.code,
  title: course.title,
  category: course.category,
  description: null,
  is_accredited: course.accredited,
  source_url: "https://wrcc.nsw.edu.au/",
  is_active: true,
}));

const OFFERINGS = [
  { start: "2026-10-03", finish: "2026-10-03", time: "8:30am – 4:30pm", location: "Griffith", places: 8, price: 185 },
  { start: "2026-10-17", finish: "2026-10-18", time: "9:00am – 3:00pm", location: "Leeton", places: 3, price: 185 },
  { start: null, finish: null, time: null, location: "Online + practical", places: null, price: 210 },
].map((offering, index) => ({
  id: `offering-${index + 1}`,
  offering_code: `HLTAID011-${index + 1}`,
  price: offering.price,
  status: "open",
  places_available: offering.places,
  places_text: offering.places === null ? null : `${offering.places} places`,
  location: offering.location,
  start_date: offering.start,
  finish_date: offering.finish,
  time_text: offering.time,
  enrollment_url: null,
}));

const PENDING_RUN = {
  id: "run-1",
  status: "pending",
  courses_found: 64,
  offerings_found: 212,
  error: null,
  started_at: iso(-0.02),
  finished_at: iso(-0.01),
  reviewed_at: null,
  created_at: iso(-0.02),
  changeset: {
    courses_added: [
      {
        course_code: "SITXFSA005",
        title: "Use Hygienic Practices for Food Safety",
        category: "Hospitality",
        description: null,
        is_accredited: true,
        source_url: null,
        offerings: [],
      },
    ],
    courses_updated: [
      {
        course_code: "HLTAID011",
        changes: { title: { from: "Provide First Aid (HLTAID011)", to: "Provide First Aid" } },
      },
    ],
    offerings_updated: [
      {
        offering_code: "HLTAID011-1",
        course_code: "HLTAID011",
        changes: { price: { from: 175, to: 185 }, places_available: { from: 12, to: 8 } },
      },
    ],
    offerings_removed: [
      {
        offering_code: "CHC-SIGN-4",
        course_code: "CHC-SIGN",
        start_date: "2026-09-20",
        location: "Hay",
        price: 95,
      },
    ],
  },
};

const BODIES = {
  direct:
    "Spring is here — and so is our next Provide First Aid course in Griffith. 🌼\n\nOne day, nationally recognised (HLTAID011), and taught by trainers who have done it for real. Places are limited to keep the practical sessions hands-on.",
  story_led:
    "Last winter, Jess from Leeton was the first person on the scene when a neighbour collapsed at the footy. She knew exactly what to do because she'd done her first aid course with us two months earlier.\n\nThat is why we run this course every month.",
  question_led:
    "Would you know what to do in the first five minutes of an emergency?\n\nOur one-day Provide First Aid course gives you the confidence to act — CPR, bleeding, burns, allergic reactions and more.",
};

type Style = keyof typeof BODIES;

function contentItem(
  id: string,
  platform: string,
  style: Style,
  status: string,
  topic: string | null,
  createdDaysAgo = 0,
) {
  return {
    id,
    platform,
    topic,
    reference_url: null,
    notes: null,
    course_id: "course-1",
    generation_group: "group-1",
    variant_style: style,
    generated_body: BODIES[style],
    edited_body: null,
    body: BODIES[style],
    hashtags: ["#WRCC", "#FirstAid", "#Griffith", "#RiverinaSkills"],
    call_to_action: "Book your place at wrcc.nsw.edu.au",
    status,
    ai_metadata: null,
    created_at: iso(-createdDaysAgo),
    updated_at: iso(-createdDaysAgo),
    reviewed_at: null,
  };
}

const STYLES: Style[] = ["direct", "story_led", "question_led"];

function generatedItems(platforms: string[]) {
  return platforms.flatMap((platform) =>
    STYLES.map((style) =>
      contentItem(`gen-${platform}-${style}`, platform, style, "draft", "Spring first aid enrolments in Griffith"),
    ),
  );
}

const HISTORY = [
  contentItem("hist-1", "facebook", "direct", "approved", "Spring first aid enrolments in Griffith", 1),
  contentItem("hist-2", "instagram", "story_led", "pending_approval", "Spring first aid enrolments in Griffith", 1),
  contentItem("hist-3", "linkedin", "question_led", "draft", "RSA refresher for hospitality staff", 2),
  contentItem("hist-4", "facebook", "story_led", "published", "Auslan for Beginners — term 4", 5),
  contentItem("hist-5", "instagram", "direct", "rejected", "Construction white card in Hay", 8),
  contentItem("hist-6", "facebook", "question_led", "archived", "Excel intermediate evening class", 21),
];

const IMAGE_COLOURS = ["#7a4f9e", "#a9bd3b", "#3f7cbf"];
const LIBRARY = ["Graduation", "Classroom", "Community"].map((name, index) => ({
  id: `asset-${index + 1}`,
  source: index === 1 ? "uploaded" : "generated",
  prompt: index === 1 ? null : `${name} photo, warm light, regional NSW`,
  model: index === 1 ? null : "gpt-image-1",
  filename: index === 1 ? "classroom.jpg" : null,
  mime_type: "image/svg+xml",
  width: 1024,
  height: index === 2 ? 768 : 1024,
  byte_size: 120_000,
  alt_text: null,
  created_at: iso(-1),
  file_url: `/api/test-media/${index}.svg`,
}));

const FACEBOOK_ACCOUNT = {
  id: "acct-fb",
  platform: "facebook",
  external_id: "1001",
  display_name: "Western Riverina Community College",
  handle: "wrccgriffith",
  scopes: ["pages_manage_posts"],
  is_active: true,
  token_expires_at: null,
  token_expired: false,
  connected_at: iso(-30),
};

const SOCIAL_ACCOUNTS = [
  FACEBOOK_ACCOUNT,
  {
    id: "acct-li",
    platform: "linkedin",
    external_id: "2001",
    display_name: "WRCC Company Page",
    handle: null,
    scopes: ["w_organization_social"],
    is_active: true,
    token_expires_at: iso(5),
    token_expired: false,
    connected_at: iso(-55),
  },
];

function imageSvg(index: number): string {
  const colour = IMAGE_COLOURS[index % IMAGE_COLOURS.length];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024"><rect width="1024" height="1024" fill="${colour}"/><circle cx="700" cy="330" r="160" fill="#ffffff" fill-opacity="0.35"/><path d="M0 820 L360 520 L620 760 L820 600 L1024 780 L1024 1024 L0 1024 Z" fill="#000000" fill-opacity="0.18"/></svg>`;
}

function preflight(platform: string) {
  const text = `${BODIES.direct}\n\nBook your place at wrcc.nsw.edu.au\n\n#WRCC #FirstAid #Griffith #RiverinaSkills`;
  return {
    ready: true,
    blockers: [],
    warnings: ["The first image is not square — Instagram-style crops may cut the edges."],
    platform,
    text,
    char_count: text.length,
    char_limit: 63_206,
    hashtag_count: 4,
    image_ids: ["asset-1", "asset-2"],
    image_required: platform === "instagram",
    max_images: 10,
    account: FACEBOOK_ACCOUNT,
  };
}

type Reply = { status?: number; json?: unknown; svg?: string };
type RouteDef = [method: string, pattern: RegExp, reply: (match: RegExpMatchArray, route: Route) => Reply];

function itemById(id: string) {
  return (
    HISTORY.find((item) => item.id === id) ??
    generatedItems(["facebook", "instagram", "linkedin"]).find((item) => item.id === id)
  );
}

const ROUTES: RouteDef[] = [
  ["GET", /^\/api\/auth\/me$/, () => ({ json: USER })],
  ["POST", /^\/api\/auth\/login$/, () => ({ json: USER })],
  ["POST", /^\/api\/auth\/logout$/, () => ({ json: { ok: true } })],
  ["GET", /^\/api\/test-media\/(\d+)\.svg$/, (m) => ({ svg: imageSvg(Number(m[1])) })],

  ["GET", /^\/api\/courses$/, () => ({ json: COURSES })],
  ["GET", /^\/api\/courses\/sync$/, () => ({ json: [PENDING_RUN] })],
  ["GET", /^\/api\/courses\/(course-\d+)$/, (m) => ({
    json: { ...COURSES.find((c) => c.id === m[1]), offerings: OFFERINGS },
  })],

  ["POST", /^\/api\/content\/generate$/, (_m, route) => {
    const body = route.request().postDataJSON() as { platforms: string[] };
    return {
      json: { generation_group: "group-1", items: generatedItems(body.platforms), warnings: [] },
    };
  }],
  ["GET", /^\/api\/content$/, () => ({ json: HISTORY })],
  ["GET", /^\/api\/content\/([\w-]+)\/media$/, () => ({
    json: {
      library: LIBRARY,
      selection: [
        { media_asset_id: "asset-1", position: 0, alt_text: null },
        { media_asset_id: "asset-2", position: 1, alt_text: null },
      ],
      max_images: 10,
    },
  })],
  ["POST", /^\/api\/content\/([\w-]+)\/images\/suggestions$/, () => ({
    json: {
      prompts: [
        "A trainer demonstrating CPR on a manikin to a small, attentive group in a bright community hall in Griffith.",
        "Close-up of hands applying a bandage during a first aid practical, warm afternoon light.",
        "Smiling adult learners holding their first aid certificates outside a regional college building.",
      ],
    },
  })],
  ["GET", /^\/api\/content\/([\w-]+)\/publications$/, (m) => ({
    json:
      m[1] === "hist-4"
        ? [{
            id: "pub-1",
            content_item_id: "hist-4",
            social_account_id: "acct-fb",
            media_asset_ids: [],
            status: "succeeded",
            external_post_id: "1001_1",
            permalink: "https://facebook.com/wrccgriffith/posts/1",
            error: null,
            error_code: null,
            request_summary: null,
            created_at: iso(-5),
            completed_at: iso(-5),
          }]
        : [],
  })],
  ["GET", /^\/api\/content\/([\w-]+)\/publish\/preflight$/, (m) => ({
    json: preflight(itemById(m[1])?.platform ?? "facebook"),
  })],
  ["GET", /^\/api\/content\/([\w-]+)$/, (m) => ({ json: itemById(m[1]) })],

  ["GET", /^\/api\/social\/accounts$/, () => ({ json: SOCIAL_ACCOUNTS })],
];

/** Answer every `/api/*` call from the fixtures above; unknown calls 404 loudly. */
export async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    for (const [routeMethod, pattern, reply] of ROUTES) {
      const match = url.pathname.match(pattern);
      if (routeMethod !== method || !match) continue;
      const { status = 200, json, svg } = reply(match, route);
      if (svg !== undefined) {
        await route.fulfill({ status, contentType: "image/svg+xml", body: svg });
      } else {
        await route.fulfill({ status, json });
      }
      return;
    }
    await route.fulfill({
      status: 404,
      json: { detail: `No fixture for ${method} ${url.pathname}` },
    });
  });
}

/** The middleware only checks that a session cookie exists. */
export async function signIn(page: Page, baseURL: string): Promise<void> {
  await page.context().addCookies([
    { name: "wrcc_session", value: "visual-capture", url: baseURL },
  ]);
}
