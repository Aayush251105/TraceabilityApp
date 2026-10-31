import type { ButtonHTMLAttributes, Ref } from "react";

type Variant = "primary" | "secondary" | "ghost" | "destructive";
type Size = "md" | "sm";

const VARIANTS: Record<Variant, string> = {
  primary: "border-accent bg-accent text-accent-fg hover:brightness-110",
  secondary: "border-border-strong bg-panel text-fg hover:bg-hover",
  ghost: "border-transparent bg-transparent text-fg2 hover:bg-hover hover:text-fg",
  destructive: "border-bad bg-bad text-panel hover:brightness-110",
};

const SIZES: Record<Size, string> = {
  md: "h-8 px-3 text-[13px]",
  sm: "h-7 px-2.5 text-[12px]",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** React 19 passes ref as a normal prop */
  ref?: Ref<HTMLButtonElement>;
}

export function Button({ variant = "secondary", size = "md", className = "", ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      className={
        "inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition-[background-color,filter,color] duration-150 " +
        "cursor-pointer disabled:cursor-not-allowed disabled:border-hover disabled:bg-hover disabled:text-fg3 disabled:hover:brightness-100 " +
        `${VARIANTS[variant]} ${SIZES[size]} ${className}`
      }
    />
  );
}
