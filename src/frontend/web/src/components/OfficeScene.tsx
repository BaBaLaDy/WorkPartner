import { useEffect, useRef, useCallback } from 'react';
import { useStore } from '../store';

/* ─────────────────────────────────────────────────────
   OfficeScene — Canvas 2D Q版办公室场景
   角色根据 team 数据在工位和休息区之间移动
   ───────────────────────────────────────────────────── */

// ── Types ───────────────────────────────────────────

interface TeamMember {
  name: string;
  display_name: string;
  description: string;
  icon: string;
  state: 'idle' | 'busy';
  current_task_title: string | null;
}

interface CharState {
  member: TeamMember;
  x: number;
  y: number;
  targetX: number;
  targetY: number;
  startX: number;
  startY: number;
  walkProgress: number; // 0→1
  mode: 'walking' | 'working' | 'resting';
  deskIndex: number;
  idleTimer: number;
  blinkTimer: number;
  isBlinking: boolean;
  breathePhase: number;
  typingPhase: number;
  currentMood: { emoji: string; zh: string; en: string };
  moodTimer: number;
  walkDir: 'left' | 'right';
}

// ── Constants ───────────────────────────────────────

const WALK_SPEED = 0.6; // progress per second (0→1)
const IDLE_MOODS: { emoji: string; zh: string; en: string }[] = [
  { emoji: '☕', zh: '正在泡咖啡', en: 'brewing coffee' },
  { emoji: '📖', zh: '翻看着笔记', en: 'skimming through notes' },
  { emoji: '🧹', zh: '整理着桌面', en: 'tidying up the desk' },
  { emoji: '🎵', zh: '轻轻哼着歌', en: 'humming a tune' },
  { emoji: '🌿', zh: '给绿植浇了点水', en: 'watering the plants' },
  { emoji: '✍️', zh: '写着随手笔记', en: 'jotting down notes' },
  { emoji: '🍵', zh: '端着茶杯发呆', en: 'daydreaming with tea' },
  { emoji: '😴', zh: '打了个小盹', en: 'taking a quick nap' },
  { emoji: '🌤️', zh: '望着窗外发呆', en: 'gazing out the window' },
];

// ── Palette generation (hash-based, same as TeamTab) ──

const PALETTES = [
  { skin: '#fde8d0', hair: '#4a3728', jacket: '#e8956a', shirt: '#fff5eb', accent: '#7cb89e' },
  { skin: '#f5d5be', hair: '#2d3a44', jacket: '#7a9aad', shirt: '#fff0e6', accent: '#d4a06a' },
  { skin: '#e8c4a8', hair: '#3d2b2c', jacket: '#b07da0', shirt: '#fef2e6', accent: '#7ea6be' },
  { skin: '#fce5c8', hair: '#7a5c42', jacket: '#8db89d', shirt: '#fff4eb', accent: '#e08a64' },
];

function getPalette(name: string) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
  return PALETTES[Math.abs(h) % PALETTES.length];
}

// ── Easing ──────────────────────────────────────────

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

// ── Drawing helpers ─────────────────────────────────

function drawRoundRect(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number, r: number,
  fill: string, stroke?: string,
) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
  if (stroke) {
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1;
    ctx.stroke();
  }
}

function drawEllipse(
  ctx: CanvasRenderingContext2D,
  cx: number, cy: number, rx: number, ry: number, fill: string,
) {
  ctx.beginPath();
  ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
  ctx.fillStyle = fill;
  ctx.fill();
}

// ── Scene drawing ───────────────────────────────────

function drawOffice(
  ctx: CanvasRenderingContext2D, w: number, h: number, isDark: boolean,
) {
  // Floor
  const floorColor = isDark ? '#2a2220' : '#f0e4d5';
  ctx.fillStyle = floorColor;
  ctx.fillRect(0, 0, w, h);

  // Floor pattern — subtle tile lines
  ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.03)' : 'rgba(139,115,85,0.08)';
  ctx.lineWidth = 1;
  const tileSize = 40;
  for (let x = 0; x < w; x += tileSize) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  for (let y = 0; y < h; y += tileSize) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }

  // Wall (top)
  const wallColor = isDark ? '#3d3028' : '#d4c4b0';
  ctx.fillStyle = wallColor;
  ctx.fillRect(0, 0, w, 32);
  ctx.fillStyle = isDark ? '#4a3a30' : '#e0d4c4';
  ctx.fillRect(0, 32, w, 4);

  // Window (top center)
  const winW = w * 0.5, winH = 20;
  const winX = (w - winW) / 2, winY = 6;
  ctx.fillStyle = isDark ? '#4a6878' : '#b8d8e8';
  ctx.fillRect(winX, winY, winW, winH);
  ctx.strokeStyle = isDark ? '#5a4838' : '#a08868';
  ctx.lineWidth = 2;
  ctx.strokeRect(winX, winY, winW, winH);
  // Window cross
  ctx.beginPath();
  ctx.moveTo(winX + winW / 2, winY);
  ctx.lineTo(winX + winW / 2, winY + winH);
  ctx.stroke();

  // Clock (top left of wall)
  const clockX = 20, clockY = 16, clockR = 10;
  drawEllipse(ctx, clockX, clockY, clockR, clockR, isDark ? '#f0e0d0' : '#fff');
  ctx.strokeStyle = isDark ? '#888' : '#555';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(clockX, clockY, clockR, 0, Math.PI * 2);
  ctx.stroke();
  // Clock hands
  const now = new Date();
  const hourAngle = (now.getHours() % 12) / 12 * Math.PI * 2 - Math.PI / 2;
  const minAngle = now.getMinutes() / 60 * Math.PI * 2 - Math.PI / 2;
  ctx.strokeStyle = isDark ? '#333' : '#333';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(clockX, clockY);
  ctx.lineTo(clockX + Math.cos(hourAngle) * 5, clockY + Math.sin(hourAngle) * 5);
  ctx.stroke();
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(clockX, clockY);
  ctx.lineTo(clockX + Math.cos(minAngle) * 7, clockY + Math.sin(minAngle) * 7);
  ctx.stroke();

  // Door (bottom right)
  const doorW = 30, doorH = 50;
  const doorX = w - 50, doorY = h - doorH - 10;
  drawRoundRect(ctx, doorX, doorY, doorW, doorH, 3, isDark ? '#5a4838' : '#a08868');
  drawRoundRect(ctx, doorX + 3, doorY + 3, doorW - 6, doorH / 2 - 3, 2, isDark ? '#4a6878' : '#c8b8a0');
  drawRoundRect(ctx, doorX + 3, doorY + doorH / 2, doorW - 6, doorH / 2 - 3, 2, isDark ? '#4a6878' : '#c8b8a0');
  // Door handle
  drawEllipse(ctx, doorX + doorW - 8, doorY + doorH / 2, 2, 2, isDark ? '#d4a06a' : '#888');
}

function drawDesk(
  ctx: CanvasRenderingContext2D, x: number, y: number, w: number, isDark: boolean,
) {
  // Chair back
  const chairColor = isDark ? '#4a3a30' : '#c8a882';
  drawRoundRect(ctx, x + 10, y + 50, w - 20, 30, 6, chairColor + '40');

  // Desk surface
  const deskColor = isDark ? '#5a4838' : '#a08868';
  drawRoundRect(ctx, x, y, w, 36, 4, deskColor);
  // Desk highlight
  ctx.fillStyle = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.15)';
  ctx.fillRect(x + 4, y + 2, w - 8, 4);

  // Computer monitor
  const monX = x + w / 2 - 12, monY = y - 18, monW = 24, monH = 16;
  ctx.fillStyle = isDark ? '#3a3a3a' : '#888';
  drawRoundRect(ctx, monX, monY, monW, monH, 2, isDark ? '#3a3a3a' : '#888');
  ctx.fillStyle = isDark ? '#1a2a3a' : '#d8e8f0';
  ctx.fillRect(monX + 2, monY + 2, monW - 4, monH - 4);
  // Stand
  ctx.fillStyle = isDark ? '#4a4a4a' : '#777';
  ctx.fillRect(monX + monW / 2 - 2, monY + monH, 4, 6);
  ctx.fillRect(monX + monW / 2 - 6, monY + monH + 4, 12, 2);
}

function drawCoffeeStation(
  ctx: CanvasRenderingContext2D, x: number, y: number, isDark: boolean,
) {
  // Table
  const tableColor = isDark ? '#5a4838' : '#b09878';
  drawRoundRect(ctx, x, y, 70, 24, 4, tableColor);

  // Coffee cup
  drawEllipse(ctx, x + 15, y + 8, 8, 8, isDark ? '#f0e0d0' : '#fff');
  ctx.fillStyle = isDark ? '#5a3828' : '#6a4828';
  drawEllipse(ctx, x + 15, y + 7, 6, 5, isDark ? '#5a3828' : '#6a4828');

  // Steam
  const t = Date.now() / 1000;
  ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.15)' : 'rgba(200,180,160,0.4)';
  ctx.lineWidth = 1.5;
  for (let i = 0; i < 3; i++) {
    const sx = x + 12 + i * 6;
    const sy = y - 4 - Math.sin(t * 2 + i) * 3;
    ctx.beginPath();
    ctx.moveTo(sx, sy + 6);
    ctx.quadraticCurveTo(sx + 3, sy + 3, sx, sy);
    ctx.stroke();
  }

  // Label
  ctx.font = '11px "Microsoft YaHei", sans-serif';
  ctx.fillStyle = isDark ? 'rgba(255,255,255,0.3)' : 'rgba(100,80,60,0.3)';
  ctx.textAlign = 'center';
  ctx.fillText('茶水台', x + 35, y + 42);
}

function drawPlant(
  ctx: CanvasRenderingContext2D, x: number, y: number, isDark: boolean,
) {
  // Pot
  drawRoundRect(ctx, x - 8, y, 16, 14, 3, isDark ? '#8a6040' : '#c4956a');

  // Leaves
  const leafColor = isDark ? '#4a7a5a' : '#627b62';
  ctx.fillStyle = leafColor;
  // Left leaf
  ctx.beginPath();
  ctx.ellipse(x - 6, y - 6, 8, 5, -0.4, 0, Math.PI * 2);
  ctx.fill();
  // Right leaf
  ctx.beginPath();
  ctx.ellipse(x + 8, y - 8, 9, 5, 0.3, 0, Math.PI * 2);
  ctx.fill();
  // Top leaf
  ctx.beginPath();
  ctx.ellipse(x + 1, y - 14, 6, 4, 0.1, 0, Math.PI * 2);
  ctx.fill();
}

// ── Character drawing ───────────────────────────────

interface DrawCharOpts {
  x: number;
  y: number;
  palette: ReturnType<typeof getPalette>;
  mode: 'walking' | 'working' | 'resting';
  walkDir: 'left' | 'right';
  blinkTimer: number;
  isBlinking: boolean;
  breathePhase: number;
  typingPhase: number;
  isDark: boolean;
  mood?: { emoji: string; zh: string; en: string };
  taskTitle?: string | null;
  scale?: number;
  locale: string;
}

function drawCharacter(
  ctx: CanvasRenderingContext2D, opts: DrawCharOpts,
) {
  const { x, y, palette, mode, blinkTimer, isBlinking, breathePhase, typingPhase, isDark, mood, taskTitle, locale, scale = 1 } = opts;
  const s = scale;

  ctx.save();
  ctx.translate(x, y);
  ctx.scale(s, s);

  // Shadow
  ctx.fillStyle = isDark ? 'rgba(0,0,0,0.2)' : 'rgba(0,0,0,0.06)';
  ctx.beginPath();
  ctx.ellipse(0, 28, 14, 4, 0, 0, Math.PI * 2);
  ctx.fill();

  // Breathing offset
  const breatheY = mode === 'resting' ? Math.sin(breathePhase) * 1 : 0;

  // Walking leg animation
  const legSwing = mode === 'walking' ? Math.sin(blinkTimer * 8) * 4 : 0;

  // ── Body ──
  const bodyY = breatheY;
  ctx.fillStyle = palette.jacket;
  ctx.beginPath();
  ctx.moveTo(-8, (12 + bodyY));
  ctx.quadraticCurveTo(-10, (22 + bodyY), -6, (28 + bodyY));
  ctx.lineTo(6, (28 + bodyY));
  ctx.quadraticCurveTo(10, (22 + bodyY), 8, (12 + bodyY));
  ctx.closePath();
  ctx.fill();

  // Shirt
  ctx.fillStyle = palette.shirt;
  ctx.beginPath();
  ctx.moveTo(-5, (14 + bodyY));
  ctx.quadraticCurveTo(0, (10 + bodyY), 5, (14 + bodyY));
  ctx.lineTo(4, (26 + bodyY));
  ctx.lineTo(-4, (26 + bodyY));
  ctx.closePath();
  ctx.fill();

  // ── Legs ──
  ctx.fillStyle = isDark ? '#3a3028' : '#5a4a3a';
  if (mode === 'walking') {
    ctx.fillRect((-4 + legSwing), (26 + bodyY), 4, 6);
    ctx.fillRect((0 - legSwing), (26 + bodyY), 4, 6);
  } else {
    ctx.fillRect(-4, (26 + bodyY), 4, 5);
    ctx.fillRect(1, (26 + bodyY), 4, 5);
  }

  // ── Arms ──
  ctx.fillStyle = palette.skin;
  if (mode === 'working') {
    const armOff = Math.sin(typingPhase * 10) * 2;
    ctx.beginPath();
    ctx.arc((-10 + armOff), (16 + bodyY), 3.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc((10 - armOff), (16 + bodyY), 3.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = palette.skin;
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo((-10 + armOff), (16 + bodyY));
    ctx.lineTo(-6, (22 + bodyY));
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo((10 - armOff), (16 + bodyY));
    ctx.lineTo(6, (22 + bodyY));
    ctx.stroke();
  } else if (mode === 'resting') {
    ctx.beginPath();
    ctx.arc(-10, (18 + bodyY), 3.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(10, (18 + bodyY), 3.5, 0, Math.PI * 2);
    ctx.fill();
  } else {
    const armSwing = Math.sin(blinkTimer * 8) * 3;
    ctx.beginPath();
    ctx.arc(-10, (16 + bodyY + armSwing), 3.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(10, (16 + bodyY - armSwing), 3.5, 0, Math.PI * 2);
    ctx.fill();
  }

  // ── Head ──
  const headY = (-8 + bodyY);
  const headR = 14;
  drawEllipse(ctx, 0, headY, headR, headR, palette.skin);

  // ── Hair ──
  ctx.fillStyle = palette.hair;
  ctx.beginPath();
  ctx.ellipse(0, headY - 8, headR + 2, headR - 2, 0, Math.PI, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(-10, headY - 2, 4, 8, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(10, headY - 2, 4, 8, 0, 0, Math.PI * 2);
  ctx.fill();

  // ── Eyes ──
  const eyeY = headY - 1;
  if (isBlinking) {
    ctx.strokeStyle = isDark ? '#ddd' : '#3d2b1f';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(-5, eyeY);
    ctx.lineTo(-2, eyeY);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(2, eyeY);
    ctx.lineTo(5, eyeY);
    ctx.stroke();
  } else if (mode === 'working') {
    ctx.fillStyle = '#fff';
    ctx.beginPath();
    ctx.ellipse(-4, eyeY + 0.5, 3, 3.5, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(4, eyeY + 0.5, 3, 3.5, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = isDark ? '#ddd' : '#3d2b1f';
    ctx.beginPath();
    ctx.ellipse(-4, eyeY + 1.5, 1.5, 2, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(4, eyeY + 1.5, 1.5, 2, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = isDark ? '#ddd' : '#3d2b1f';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(-6, eyeY - 5);
    ctx.lineTo(-2, eyeY - 4);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(2, eyeY - 4);
    ctx.lineTo(6, eyeY - 5);
    ctx.stroke();
  } else {
    ctx.strokeStyle = isDark ? '#ddd' : '#3d2b1f';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(-4, eyeY, 3, 0, Math.PI);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(4, eyeY, 3, 0, Math.PI);
    ctx.stroke();
  }

  // ── Blush ──
  ctx.fillStyle = '#f7a8a8';
  ctx.globalAlpha = mode === 'resting' ? 0.4 : 0.2;
  ctx.beginPath();
  ctx.ellipse(-8, eyeY + 5, 3, 2, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(8, eyeY + 5, 3, 2, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;

  // ── Mouth ──
  ctx.strokeStyle = isDark ? '#d48a7a' : '#c47a6a';
  ctx.lineWidth = 1.5;
  ctx.lineCap = 'round';
  if (mode === 'working') {
    ctx.beginPath();
    ctx.moveTo(-3, eyeY + 8);
    ctx.lineTo(3, eyeY + 8);
    ctx.stroke();
  } else if (mode === 'resting') {
    ctx.beginPath();
    ctx.arc(0, eyeY + 6, 4, 0, Math.PI);
    ctx.stroke();
  } else {
    ctx.beginPath();
    ctx.moveTo(-3, eyeY + 7);
    ctx.lineTo(3, eyeY + 7);
    ctx.stroke();
  }

  // ── Speech bubble ──
  if (mood || taskTitle) {
    const text = mood
      ? locale === 'en' ? mood.en : mood.zh
      : taskTitle ?? '';
    ctx.font = '10px "Microsoft YaHei", sans-serif';
    const tw = ctx.measureText(text).width;
    const bw = Math.max(tw + 16, 50);
    const bh = 20;
    const bx = -bw / 2;
    const by = (-36 + bodyY);

    ctx.fillStyle = isDark ? 'rgba(40,30,24,0.85)' : 'rgba(255,252,245,0.9)';
    drawRoundRect(ctx, bx, by, bw, bh, 6, ctx.fillStyle, isDark ? 'rgba(255,255,255,0.1)' : 'rgba(180,160,140,0.3)');

    // Bubble tail
    ctx.fillStyle = isDark ? 'rgba(40,30,24,0.85)' : 'rgba(255,252,245,0.9)';
    ctx.beginPath();
    ctx.moveTo(0, by + bh);
    ctx.lineTo(-4, by + bh + 6);
    ctx.lineTo(4, by + bh + 6);
    ctx.closePath();
    ctx.fill();

    ctx.fillStyle = isDark ? 'rgba(255,255,255,0.8)' : 'rgba(80,60,40,0.8)';
    ctx.textAlign = 'center';
    ctx.fillText(text, 0, by + bh / 2 + 3.5);
  }

  // ── State indicator dot ──
  if (mode === 'working') {
    drawEllipse(ctx, 12, (-22 + bodyY), 3, 3, '#627b62');
    drawEllipse(ctx, 12, (-22 + bodyY), 1.5, 1.5, '#8fc4a8');
  }

  ctx.restore();
}

// ── Main Component ──────────────────────────────────

interface OfficeSceneProps {
  team: TeamMember[];
}

export function OfficeScene({ team }: OfficeSceneProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const charsRef = useRef<Map<string, CharState>>(new Map());
  const rafRef = useRef<number>(0);
  const sizeRef = useRef({ w: 900, h: 360 });
  const teamRef = useRef(team);
  const isDarkRef = useRef(false);
  const localeRef = useRef('zh');

  const isDark = useStore((s) => s.theme === 'dark');
  const locale = useStore((s) => s.locale);

  // Keep refs in sync
  useEffect(() => { teamRef.current = team; }, [team]);
  useEffect(() => { isDarkRef.current = isDark; }, [isDark]);
  useEffect(() => { localeRef.current = locale; }, [locale]);

  // ── Desk/rest positions (fixed, no canvasSize dependency) ──
  const deskPositions = [
    { x: 80, y: 80 },
    { x: 220, y: 80 },
    { x: 360, y: 80 },
    { x: 500, y: 80 },
  ];

  const getRestPositions = (w: number, h: number) => [
    { x: w - 140, y: h - 90 },
    { x: w - 140, y: h - 130 },
    { x: 60, y: h - 90 },
    { x: w / 2 - 30, y: h - 100 },
  ];

  // ── Sync characters when team changes ──────────────
  useEffect(() => {
    const chars = charsRef.current;
    const { w, h } = sizeRef.current;
    const restPositions = getRestPositions(w, h);

    // Remove departed members
    const teamNames = new Set(team.map((m) => m.name));
    for (const name of chars.keys()) {
      if (!teamNames.has(name)) {
        chars.delete(name);
      }
    }

    // Add new members or update existing
    team.forEach((member, i) => {
      let ch = chars.get(member.name);
      if (!ch) {
        const rest = restPositions[i % restPositions.length];
        ch = {
          member,
          x: rest.x,
          y: rest.y,
          targetX: rest.x,
          targetY: rest.y,
          startX: rest.x,
          startY: rest.y,
          walkProgress: 1,
          mode: 'resting',
          deskIndex: i,
          idleTimer: Math.random() * 5,
          blinkTimer: 0,
          isBlinking: false,
          breathePhase: Math.random() * Math.PI * 2,
          typingPhase: Math.random() * Math.PI * 2,
          currentMood: IDLE_MOODS[Math.floor(Math.random() * IDLE_MOODS.length)],
          moodTimer: 8 + Math.random() * 12,
          walkDir: 'right',
        };
        chars.set(member.name, ch);
      } else {
        ch.member = member;
      }

      // Update target based on state
      if (member.state === 'busy') {
        if (ch.mode !== 'working' && ch.walkProgress >= 1) {
          const desk = deskPositions[i % deskPositions.length];
          ch.startX = ch.x;
          ch.startY = ch.y;
          ch.targetX = desk.x;
          ch.targetY = desk.y;
          ch.walkProgress = 0;
          ch.walkDir = ch.x < desk.x ? 'right' : 'left';
        }
      } else {
        if (ch.mode !== 'resting' && ch.walkProgress >= 1) {
          const rpos = getRestPositions(w, h);
          const rest = rpos[i % rpos.length];
          ch.startX = ch.x;
          ch.startY = ch.y;
          ch.targetX = rest.x;
          ch.targetY = rest.y;
          ch.walkProgress = 0;
          ch.walkDir = ch.x < rest.x ? 'right' : 'left';
          ch.currentMood = IDLE_MOODS[Math.floor(Math.random() * IDLE_MOODS.length)];
        }
      }
    });
  }, [team]);

  // ── Game loop (no React deps, reads from refs) ────
  const gameLoop = useCallback(
    () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const { w, h } = sizeRef.current;
      const dark = isDarkRef.current;
      const loc = localeRef.current;
      const chars = charsRef.current;

      // Update characters
      for (const ch of chars.values()) {
        // Walking
        if (ch.walkProgress < 1) {
          ch.walkProgress = Math.min(1, ch.walkProgress + WALK_SPEED * 0.016);
          const t = easeInOutCubic(ch.walkProgress);
          ch.x = ch.startX + (ch.targetX - ch.startX) * t;
          ch.y = ch.startY + (ch.targetY - ch.startY) * t;

          if (ch.walkProgress >= 1) {
            ch.x = ch.targetX;
            ch.y = ch.targetY;
            ch.mode = ch.member.state === 'busy' ? 'working' : 'resting';
          }
        }

        // Animation timers
        ch.blinkTimer += 0.016;
        ch.breathePhase += 0.016 * 2;
        ch.typingPhase += 0.016;

        // Blink
        ch.isBlinking = Math.sin(ch.blinkTimer * 3) > 0.95;

        // Mood rotation (idle only)
        if (ch.mode === 'resting') {
          ch.moodTimer -= 0.016;
          if (ch.moodTimer <= 0) {
            ch.currentMood = IDLE_MOODS[Math.floor(Math.random() * IDLE_MOODS.length)];
            ch.moodTimer = 8 + Math.random() * 12;
          }
        }
      }

      // ── Render ──
      ctx.imageSmoothingEnabled = false;
      ctx.clearRect(0, 0, w, h);

      // Draw office
      drawOffice(ctx, w, h, dark);

      // Draw plants
      drawPlant(ctx, 40, h - 50, dark);
      drawPlant(ctx, w - 90, h - 50, dark);

      // Draw coffee station
      drawCoffeeStation(ctx, w - 160, h - 80, dark);

      // Draw desks
      const dpos = deskPositions;
      for (let i = 0; i < dpos.length; i++) {
        const desk = dpos[i];
        drawDesk(ctx, desk.x - 40, desk.y - 20, 80, dark);
      }

      // Sort characters by Y for z-ordering
      const sorted = [...chars.values()].sort((a, b) => a.y - b.y);

      // Draw characters
      for (const ch of sorted) {
        const palette = getPalette(ch.member.name);
        drawCharacter(ctx, {
          x: ch.x,
          y: ch.y,
          palette,
          mode: ch.mode,
          walkDir: ch.walkDir,
          blinkTimer: ch.blinkTimer,
          isBlinking: ch.isBlinking,
          breathePhase: ch.breathePhase,
          typingPhase: ch.typingPhase,
          isDark: dark,
          mood: ch.mode === 'resting' ? ch.currentMood : undefined,
          taskTitle: ch.mode === 'working' ? ch.member.current_task_title : undefined,
          locale: loc,
        });
      }

      rafRef.current = requestAnimationFrame(gameLoop);
    },
    [], // stable — reads from refs
  );

  // ── Canvas sizing + loop start ────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const resize = () => {
      const rect = canvas.parentElement?.getBoundingClientRect();
      const w = Math.max(900, rect?.width || 900);
      const h = Math.max(360, Math.min(420, (rect?.height || 360) * 0.7));
      canvas.width = w;
      canvas.height = h;
      sizeRef.current = { w, h };
    };

    resize();
    const observer = new ResizeObserver(resize);
    if (canvas.parentElement) observer.observe(canvas.parentElement);

    rafRef.current = requestAnimationFrame(gameLoop);

    return () => {
      cancelAnimationFrame(rafRef.current);
      observer.disconnect();
    };
  }, [gameLoop]);

  return (
    <div className="office-scene-wrapper">
      <canvas ref={canvasRef} className="office-canvas" />
      {team.length === 0 && (
        <div className="office-empty">
          <span className="office-empty-emoji">🏠</span>
          <span>
            {localeRef.current === 'zh' ? '办公室很安静，角色们还没就位...' : 'The office is quiet — characters haven\'t arrived yet.'}
          </span>
        </div>
      )}
    </div>
  );
}
