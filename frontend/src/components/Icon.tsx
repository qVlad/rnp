/**
 * Единый Icon wrapper над lucide-react.
 *
 * Использование:
 *   <Icon name="download" size={14} />
 *   <Icon name="trash-2" size={12} className="text-danger" />
 *
 * Размер по умолчанию 14px (text-sm), color: currentColor.
 * Stroke 1.5 (Lucide default).
 *
 * Карта имён ниже — semantic alias-ы для нашего домена, чтобы при
 * замене иконок не лазить по 30 файлам.
 */
import {
  AlertCircle,
  AlertTriangle,
  Archive,
  ArrowDown,
  ArrowUp,
  Bell,
  Calendar,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  Eye,
  EyeOff,
  FileSpreadsheet,
  FileText,
  Filter,
  HelpCircle,
  Image as ImageIcon,
  Info,
  Layers,
  Link as LinkIcon,
  ListChecks,
  LogOut,
  Loader2,
  Menu,
  Package,
  Pencil,
  Plus,
  RefreshCw,
  Ruler,
  Save,
  Search,
  Settings,
  Sparkles,
  Star,
  Trash2,
  TrendingDown,
  TrendingUp,
  Upload,
  X,
} from "lucide-react";

const ICONS = {
  // Status / states
  "info": Info,
  "warning": AlertTriangle,
  "alert": AlertCircle,
  "check": Check,
  "close": X,
  // Navigation / UI
  "menu": Menu,
  "chevron-down": ChevronDown,
  "chevron-right": ChevronRight,
  "help": HelpCircle,
  "search": Search,
  "settings": Settings,
  "filter": Filter,
  "layers": Layers,
  "list": ListChecks,
  // Data / actions
  "calendar": Calendar,
  "download": Download,
  "upload": Upload,
  "save": Save,
  "copy": Copy,
  "trash": Trash2,
  "edit": Pencil,
  "plus": Plus,
  "refresh": RefreshCw,
  "link": LinkIcon,
  "logout": LogOut,
  // Trend
  "trend-up": TrendingUp,
  "trend-down": TrendingDown,
  "arrow-up": ArrowUp,
  "arrow-down": ArrowDown,
  // Domain
  "package": Package,
  "archive": Archive,
  "ruler": Ruler,
  "bell": Bell,
  "eye": Eye,
  "eye-off": EyeOff,
  "star": Star,
  "sparkles": Sparkles,
  "pdf": FileText,
  "png": ImageIcon,
  "xlsx": FileSpreadsheet,
  // Loading
  "spinner": Loader2,
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({
  name,
  size = 14,
  className = "",
  strokeWidth = 1.75,
  ...rest
}: {
  name: IconName;
  size?: number;
  className?: string;
  strokeWidth?: number;
} & Omit<React.SVGAttributes<SVGSVGElement>, "name">) {
  const Cmp = ICONS[name];
  if (!Cmp) {
    // eslint-disable-next-line no-console
    console.warn(`Icon: unknown name "${name}"`);
    return null;
  }
  return <Cmp size={size} strokeWidth={strokeWidth} className={className} aria-hidden {...rest} />;
}

export default Icon;
