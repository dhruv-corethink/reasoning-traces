# Performance Optimization

**Category:** Frontend (React/Tailwind) · `frontend_04_performance_optimization`

| Condition | Score /10 |
|---|---|
| Claude Haiku 4.5 alone | **2** |
| Claude Haiku 4.5 + `/reason` | **5** |
| Delta | **+3** — judge pick: **WITH** |

_Judge (openai/gpt-5, blind pairwise):_ Candidate A delivers a complete, accessible modal with focus trapping and Tailwind, but the dropdown menu is incomplete and truncated, so the overall solution doesn't fully meet the brief. Candidate B provides a project scaffold and some hooks, but most components (including the modal and dropdown content/trigger) are missing or cut off, making it far from a working implementation.

---

## Task
Build a fully accessible dropdown navigation menu and modal component using React and Tailwind v3, including keyboard navigation, ARIA roles, focus trapping, and screen reader support.

---

## WITHOUT — Claude Haiku 4.5 alone
# Accessible Dropdown Navigation and Modal Components

I'll build a comprehensive solution with dropdown navigation and modal components that meet WCAG 2.1 AA standards.

## Project Structure

```
src/
├── components/
│   ├── DropdownMenu/
│   │   ├── DropdownMenu.tsx
│   │   ├── DropdownTrigger.tsx
│   │   ├── DropdownContent.tsx
│   │   └── useDropdownMenu.ts
│   ├── Modal/
│   │   ├── Modal.tsx
│   │   ├── ModalHeader.tsx
│   │   ├── ModalBody.tsx
│   │   ├── ModalFooter.tsx
│   │   └── useModal.ts
│   ├── Navigation/
│   │   └── NavigationBar.tsx
│   └── Examples.tsx
├── hooks/
│   ├── useFocusTrap.ts
│   ├── useKeyboardNavigation.ts
│   └── useOutsideClick.ts
├── utils/
│   └── accessibility.ts
└── App.tsx
```

## 1. Utility Functions for Accessibility

```typescript
// src/utils/accessibility.ts
export const KEYS = {
  ENTER: 'Enter',
  SPACE: ' ',
  ESCAPE: 'Escape',
  ARROW_UP: 'ArrowUp',
  ARROW_DOWN: 'ArrowDown',
  ARROW_LEFT: 'ArrowLeft',
  ARROW_RIGHT: 'ArrowRight',
  HOME: 'Home',
  END: 'End',
  TAB: 'Tab',
} as const;

/**
 * Get all focusable elements within a container
 */
export const getFocusableElements = (
  container: HTMLElement | null
): HTMLElement[] => {
  if (!container) return [];

  const focusableSelectors = [
    'a[href]',
    'button:not([disabled])',
    'textarea:not([disabled])',
    'input[type="text"]:not([disabled])',
    'input[type="radio"]:not([disabled])',
    'input[type="checkbox"]:not([disabled])',
    'select:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');

  return Array.from(container.querySelectorAll(focusableSelectors));
};

/**
 * Announce message to screen readers
 */
export const announceToScreenReader = (
  message: string,
  priority: 'polite' | 'assertive' = 'polite'
): void => {
  const announcement = document.createElement('div');
  announcement.setAttribute('role', 'status');
  announcement.setAttribute('aria-live', priority);
  announcement.setAttribute('aria-atomic', 'true');
  announcement.className = 'sr-only';
  announcement.textContent = message;

  document.body.appendChild(announcement);

  setTimeout(() => {
    document.body.removeChild(announcement);
  }, 1000);
};

/**
 * Generate unique ID
 */
export const generateId = (prefix: string): string => {
  return `${prefix}-${Math.random().toString(36).substr(2, 9)}`;
};
```

## 2. Custom Hooks

```typescript
// src/hooks/useFocusTrap.ts
import { useEffect, useRef } from 'react';
import { getFocusableElements, KEYS } from '../utils/accessibility';

interface UseFocusTrapProps {
  isActive: boolean;
  onEscape?: () => void;
}

export const useFocusTrap = ({
  isActive,
  onEscape,
}: UseFocusTrapProps) => {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!isActive) return;

    const element = ref.current;
    if (!element) return;

    const focusableElements = getFocusableElements(element);

    if (focusableElements.length === 0) {
      element.focus();
      return;
    }

    const firstElement = focusableElements[0] as HTMLElement;
    const lastElement = focusableElements[
      focusableElements.length - 1
    ] as HTMLElement;

    // Focus first element
    firstElement.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === KEYS.ESCAPE) {
        e.preventDefault();
        onEscape?.();
        return;
      }

      if (e.key === KEYS.TAB) {
        if (e.shiftKey) {
          // Shift + Tab
          if (document.activeElement === firstElement) {
            e.preventDefault();
            lastElement.focus();
          }
        } else {
          // Tab
          if (document.activeElement === lastElement) {
            e.preventDefault();
            firstElement.focus();
          }
        }
      }
    };

    element.addEventListener('keydown', handleKeyDown);
    return () => {
      element.removeEventListener('keydown', handleKeyDown);
    };
  }, [isActive, onEscape]);

  return ref;
};
```

```typescript
// src/hooks/useKeyboardNavigation.ts
import { useEffect, useCallback } from 'react';
import { KEYS } from '../utils/accessibility';

interface UseKeyboardNavigationProps {
  isOpen: boolean;
  onKeyDown?: (key: string, event: KeyboardEvent) => void;
}

export const useKeyboardNavigation = ({
  isOpen,
  onKeyDown,
}: UseKeyboardNavigationProps) => {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isOpen) return;

      onKeyDown?.(e.key, e);
    },
    [isOpen, onKeyDown]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [handleKeyDown]);
};

/**
 * Navigation within a list of items
 */
export const useListKeyboardNavigation = (
  items: HTMLElement[],
  selectedIndex: number,
  onSelect: (index: number) => void
) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      let newIndex = selectedIndex;

      switch (e.key) {
        case KEYS.ARROW_DOWN:
          e.preventDefault();
          newIndex = (selectedIndex + 1) % items.length;
          break;
        case KEYS.ARROW_UP:
          e.preventDefault();
          newIndex =
            selectedIndex === 0 ? items.length - 1 : selectedIndex - 1;
          break;
        case KEYS.HOME:
          e.preventDefault();
          newIndex = 0;
          break;
        case KEYS.END:
          e.preventDefault();
          newIndex = items.length - 1;
          break;
        default:
          return;
      }

      onSelect(newIndex);
      items[newIndex]?.focus();
    };

    if (items.length > 0) {
      items[selectedIndex]?.addEventListener('keydown', handleKeyDown);

      return () => {
        items[selectedIndex]?.removeEventListener('keydown', handleKeyDown);
      };
    }
  }, [items, selectedIndex, onSelect]);
};
```

```typescript
// src/hooks/useOutsideClick.ts
import { useEffect, useRef } from 'react';

interface UseOutsideClickProps {
  onOutsideClick: () => void;
  isActive?: boolean;
}

export const useOutsideClick = ({
  onOutsideClick,
  isActive = true,
}: UseOutsideClickProps) => {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!isActive) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (
        ref.current &&
        !ref.current.contains(event.target as Node)
      ) {
        onOutsideClick();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isActive, onOutsideClick]);

  return ref;
};
```

## 3. Dropdown Menu Components

```typescript
// src/hooks/useDropdownMenu.ts
import { useState, useCallback } from 'react';
import { KEYS } from '../utils/accessibility';

export const useDropdownMenu = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const open = useCallback(() => {
    setIsOpen(true);
    setSelectedIndex(0);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
  }, []);

  const toggle = useCallback(() => {
    setIsOpen((prev) => !prev);
  }, []);

  const selectItem = useCallback((index: number) => {
    setSelectedIndex(index);
  }, []);

  return {
    isOpen,
    open,
    close,
    toggle,
    selectedIndex,
    selectItem,
  };
};
```

```typescript
// src/components/DropdownMenu/DropdownMenu.tsx
import React, { ReactNode, useRef } from 'react';
import { useOutsideClick } from '../../hooks/useOutsideClick';
import { generateId } from '../../utils/accessibility';

interface DropdownMenuProps {
  children: ReactNode;
  isOpen: boolean;
  onClose: () => void;
}

export const DropdownMenu: React.FC<DropdownMenuProps> = ({
  children,
  isOpen,
  onClose,
}) => {
  const ref = useOutsideClick({
    onOutsideClick: onClose,
    isActive: isOpen,
  });

  const menuId = useRef(generateId('dropdown-menu')).current;

  return (
    <div
      ref={ref as React.RefObject<HTMLDivElement>}
      className="relative inline-block"
    >
      {children}
    </div>
  );
};
```

```typescript
// src/components/DropdownMenu/DropdownTrigger.tsx
import React from 'react';
import { KEYS } from '../../utils/accessibility';

interface DropdownTriggerProps {
  onClick: () => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLButtonElement>) => void;
  isOpen: boolean;
  menuId: string;
  children: React.ReactNode;
  disabled?: boolean;
}

export const DropdownTrigger: React.FC<DropdownTriggerProps> = ({
  onClick,
  onKeyDown,
  isOpen,
  menuId,
  children,
  disabled = false,
}) => {
  const handleKeyDown = (
    e: React.KeyboardEvent<HTML

---

## WITH — Claude Haiku 4.5 + `/reason` trace (Claude Opus 4.8 (proxy for Corethink))
# Accessible Dropdown Navigation & Modal Components

I'll build production-ready, fully accessible React components with comprehensive keyboard navigation, ARIA support, focus management, and screen reader compatibility.

## 1. Focus Trap Hook

```jsx
// hooks/useFocusTrap.js
import { useEffect, useRef } from 'react';

const FOCUSABLE_SELECTORS = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export function useFocusTrap(isActive) {
  const containerRef = useRef(null);
  const previouslyFocused = useRef(null);

  useEffect(() => {
    if (!isActive) return;

    previouslyFocused.current = document.activeElement;
    const container = containerRef.current;
    if (!container) return;

    // Get all focusable elements that are visible
    const getFocusable = () =>
      Array.from(container.querySelectorAll(FOCUSABLE_SELECTORS)).filter(
        (el) => el.offsetParent !== null
      );

    const focusable = getFocusable();
    if (focusable.length > 0) {
      focusable[0].focus();
    } else {
      container.focus();
    }

    const handleKeyDown = (e) => {
      if (e.key !== 'Tab') return;

      const nodes = getFocusable();
      if (nodes.length === 0) {
        e.preventDefault();
        return;
      }

      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      const activeElement = document.activeElement;

      if (e.shiftKey && activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    container.addEventListener('keydown', handleKeyDown);

    return () => {
      container.removeEventListener('keydown', handleKeyDown);
      if (previouslyFocused.current instanceof HTMLElement) {
        previouslyFocused.current.focus();
      }
    };
  }, [isActive]);

  return containerRef;
}
```

## 2. Modal Component

```jsx
// components/Modal.jsx
import { useEffect, useId } from 'react';
import { createPortal } from 'react-dom';
import { useFocusTrap } from '../hooks/useFocusTrap';

export function Modal({
  isOpen,
  onClose,
  title,
  description,
  children,
  size = 'md',
}) {
  const trapRef = useFocusTrap(isOpen);
  const titleId = useId();
  const descriptionId = useId();

  // Handle Escape key and body scroll lock
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    const scrollbarWidth =
      window.innerWidth - document.documentElement.clientWidth;
    const originalOverflow = document.body.style.overflow;
    const originalPaddingRight = document.body.style.paddingRight;

    document.body.style.overflow = 'hidden';
    document.body.style.paddingRight = `${scrollbarWidth}px`;

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = originalOverflow;
      document.body.style.paddingRight = originalPaddingRight;
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const sizeClasses = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
      role="presentation"
    >
      {/* Backdrop with blur */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
        aria-hidden="true"
      />

      {/* Modal Dialog */}
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className={`relative z-10 w-full ${sizeClasses[size]} rounded-lg bg-white
                     p-6 shadow-2xl focus:outline-none dark:bg-gray-800`}
      >
        {/* Header */}
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2
              id={titleId}
              className="text-lg font-semibold text-gray-900 dark:text-white"
            >
              {title}
            </h2>
            {description && (
              <p
                id={descriptionId}
                className="mt-1 text-sm text-gray-600 dark:text-gray-400"
              >
                {description}
              </p>
            )}
          </div>

          {/* Close Button */}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="ml-4 inline-flex flex-shrink-0 items-center justify-center
                       rounded-md p-1.5 text-gray-400 transition-colors
                       hover:bg-gray-100 hover:text-gray-600 focus:outline-none
                       focus-visible:ring-2 focus-visible:ring-blue-500
                       focus-visible:ring-offset-2 dark:hover:bg-gray-700
                       dark:focus-visible:ring-offset-gray-800"
          >
            <svg
              className="h-5 w-5"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                clipRule="evenodd"
              />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="text-gray-600 dark:text-gray-300">{children}</div>
      </div>
    </div>,
    document.body
  );
}
```

## 3. Dropdown Menu Component

```jsx
// components/DropdownMenu.jsx
import { useState, useRef, useEffect, useCallback, useId } from 'react';

export function DropdownMenu({ label, items, placement = 'left' }) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const buttonRef = useRef(null);
  const menuRef = useRef(null);
  const itemRefs = useRef([]);
  const menuId = useId();
  const searchTimeoutRef = useRef(null);
  const searchStringRef = useRef('');

  const openMenu = useCallback((initialIndex = 0) => {
    setIsOpen(true);
    setActiveIndex(initialIndex);
  }, []);

  const closeMenu = useCallback((returnFocus = true) => {
    setIsOpen(false);
    setActiveIndex(-1);
    searchStringRef.current = '';
    if (returnFocus && buttonRef.current) {
      buttonRef.current.focus();
    }
  }, []);

  // Move DOM focus to the currently active item
  useEffect(() => {
    if (isOpen && activeIndex >= 0 && itemRefs.current[activeIndex]) {
      itemRefs.current[activeIndex].focus();
    }
  }, [isOpen, activeIndex]);

  // Close menu when clicking outside
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e) => {
      if (
        !menuRef.current?.contains(e.target) &&
        !buttonRef.current?.contains(e.target)
      ) {
        closeMenu(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen, closeMenu]);

  // Keyboard navigation on trigger button
  const handleButtonKeyDown = (e) => {
    switch (e.key) {
      case 'ArrowDown':
      case 'Enter':
      case ' ':
        e.preventDefault();
        openMenu(0);
        break;
      case 'ArrowUp':
        e.preventDefault();
        openMenu(items.length - 1);
        break;
      default:
        break;
    }
  };

  // Keyboard navigation within menu
  const handleMenuKeyDown = (e) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setActiveIndex((i) => (i + 1) % items.length);
        break;
      case 'ArrowUp':
        e.preventDefault();
        setActiveIndex((i) => (i - 1 + items.length) % items.length);
        break;
      case 'Home':
        e.preventDefault();
        setActiveIndex(0);
        break;
      case 'End':
        e.preventDefault();
        setActiveIndex(items.length - 1);
        break;
      case 'Enter':
      case ' ':
        e.preventDefault();
        if (activeIndex >= 0) {
          handleItemClick(items[activeIndex]);
        }
        break;
      case 'Escape':
        e.preventDefault();
        closeMenu();
        break;
      case 'Tab':
        closeMenu(false);
        break;
      default:
        // Type-ahead search
        if (e.key.length === 1 && /[a-zA-Z0-9]/.test(e.key)) {
          e.preventDefault();
          searchStringRef.current += e.key.toLowerCase();

          clearTimeout(searchTimeoutRef.current);
          searchTimeoutRef.current =

---

<details><summary>Reasoning trace supplied to Haiku</summary>

I need to build fully accessible dropdown and modal components with React and Tailwind, making sure to include keyboard navigation, ARIA attributes, focus management, and screen reader support throughout.

**Conclusion:** # Accessible Dropdown Navigation & Modal Components

Here's a complete, production-ready implementation with full accessibility support.

## 1. Custom Hook: Focus Trap

```jsx
// hooks/useFocusTrap.js
import { useEffect, useRef } from 'react';

const FOCUSABLE_SELECTORS = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export function useFocusTrap(isActive) {
  const containerRef = useRef(null);
  // Store the element that had focus before trapping, to restore later
  const previouslyFocused = useRef(null);

  useEffect(() => {
    if (!isActive) return;

    previouslyFocused.current = document.activeElement;
    const container = containerRef.current;
    if (!container) return;

    const getFocusable = () =>
      Array.from(container.querySelectorAll(FOCUSABLE_SELECTORS)).filter(
        (el) => el.offsetParent !== null // visible only
      );

    // Move focus into the trap
    const focusable = getFocusable();
    (focusable[0] || container).focus();

    const handleKeyDown = (e) => {
      if (e.key !== 'Tab') return;

      const nodes = getFocusable();
      if (nodes.length === 0) {
        e.preventDefault();
        return;
      }

      const first = nodes[0];
      const last = nodes[nodes.length - 1];

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    container.addEventListener('keydown', handleKeyDown);

    return () => {
      container.removeEventListener('keydown', handleKeyDown);
      // Restore focus to the trigger element
      if (previouslyFocused.current instanceof HTMLElement) {
        previouslyFocused.current.focus();
      }
    };
  }, [isActive]);

  return containerRef;
}
```

## 2. Modal Component

```jsx
// components/Modal.jsx
import { useEffect, useId } from 'react';
import { createPortal } from 'react-dom';
import { useFocusTrap } from '../hooks/useFocusTrap';

export function Modal({ isOpen, onClose, title, children }) {
  const trapRef = useFocusTrap(isOpen);
  const titleId = useId();
  const descId = useId();

  // Close on Escape + lock body scroll while open
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };

    document.addEventListener('keydown', handleKeyDown);
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = originalOverflow;
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      // Clicking the backdrop closes the modal
      onClick={onClose}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        aria-hidden="true"
      />

      {/* Dialog */}
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()} // prevent backdrop close
        className="relative z-10 w-full max-w-md rounded-lg bg-white p-6 shadow-xl
                   focus:outline-none dark:bg-gray-800"
      >
        <div className="mb-4 flex items-start justify-between">
          <h2
            id={titleId}
            className="text-lg font-semibold text-gray-900 dark:text-white"
          >
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="ml-4 rounded-md p-1 text-gray-400 hover:bg-gray-100
                       hover:text-gray-600 focus:outline-none focus-visible:ring-2
                       focus-visible:ring-blue-500 dark:hover:bg-gray-700"
          >
            <svg
              className="h-5 w-5"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        </div>

        <div id={descId} className="text-gray-600 dark:text-gray-300">
          {children}
        </div>
      </div>
    </div>,
    document.body
  );
}
```

## 3. Dropdown Menu Component

```jsx
// components/DropdownMenu.jsx
import { useState, useRef, useEffect, useCallback, useId } from 'react';

export function DropdownMenu({ label, items }) {
  const [isOpen, setIsOpen] = useState(false);
  // Track which menu item is "active" for keyboard navigation
  const [activeIndex, setActiveIndex] = useState(-1);

  const buttonRef = useRef(null);
  const menuRef = useRef(null);
  const itemRefs = useRef([]);
  const menuId = useId();

  const openMenu = useCallback((index = 0) => {
    setIsOpen(true);
    setActiveIndex(index);
  }, []);

  const closeMenu = useCallback((refocus = true) => {
    setIsOpen(false);
    setActiveIndex(-1);
    if (refocus) buttonRef.current?.focus();
  }, []);

  // Move DOM focus to the active item when it changes
  useEffect(() => {
    if (isOpen && activeIndex >= 0) {
      itemRefs.current[activeIndex]?.focus();
    }
  }, [isOpen, activeIndex]);

  // Close when clicking outside
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e) => {
      if (
        !menuRef.current?.contains(e.target) &&
        !buttonRef.current?.contains(e.target)
      ) {
        closeMenu(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen, closeMenu]);

  // Keyboard behavior on the trigger button
  const handleButtonKeyDown = (e) => {
    switch (e.key) {
      case 'ArrowDown':
      case 'Enter':
      case ' ':
        e.preventDefault();
        openMenu(0);
        break;
      case 'ArrowUp':
        e.preventDefault();
        openMenu(items.length - 1); // open at last item
        break;
      default:
        break;
    }
  };

  // Keyboard behavior while navigating the menu
  const handleMenuKeyDown = (e) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setActiveIndex((i) => (i + 1) % items.length);
        break;
      case 'ArrowUp':
        e.preventDefault();
        setActiveIndex((i) => (i - 1 + items.length) % items.length);
        break;
      case 'Home':
        e.preventDefault();
        setActiveIndex(0);
        break;
      case 'End':
        e.preventDefault();
        setActiveIndex(items.length - 1);
        break;
      case 'Escape':
        e.preventDefault();
        closeMenu();
        break;
      case 'Tab':
        // Tab closes the menu (standard menu behavior)
        closeMenu(false);
        break;
      default:
        // Type-ahead: jump to item starting with typed letter
        if (e.key.length === 1 && /\S/.test(e.key)) {
          const idx = items.findIndex((item) =>
            item.label.toLowerCase().startsWith(e.key.toLowerCase())
          );
          if (idx >= 0) setActiveIndex(idx);
        }
        break;
    }
  };

  const handleItemClick = (item) => {
    item.onSelect?.();
    closeMenu();
  };

  return (
    <div className="relative inline-block text-left">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-controls={isOpen ? menuId : undefined}
        onClick={() => (isOpen ? closeMenu() : openMenu(0))}
        onKeyDown={handleButtonKeyDown}
        className="inline-flex items-center gap-2 rounded-md bg-white px-4 py-2
                   text-sm font-medium text-gray-700 shadow-sm ring-1 ring-gray-300
                   hover:bg-gray-50 focus:outline-none focus-visible:ring-2
                   focus-visible:ring-blue-500 dark:bg-gray-800 dark:text-gray-200
                   dark:ring-gray-600 dark:hover:bg-gray-700"
      >
        {label}
        <svg
          className={`h-4 w-4 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
        >
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 0 1 1.06.02L10 11.17l3.71-3.94a.75.75 0 1 1 1.08 1.04l-4.25 4.5a.75.75 0 0 1-1.08 0l-4.25-4.5a.75.75 0 0 1 .02-1.06Z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {isOpen && (
        <ul
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-orientation="vertical"
          aria-label={label}
          onKeyDown={handleMenuKeyDown}
          className="absolute left-0 z-20 mt-2 w-56 origin-top-left rounded-md
                     bg-white py-1 shadow-lg ring-1 ring-black/5 focus:outline-none
                     dark:bg-gray-800 dark:ring-white/10"
        >
          {items.map((item, index) => (
            <li key={item.id ?? index} role="none">
              <button
                ref={(el) => (itemRefs.current[index] = el)}
                role="menuitem"
                tabIndex={activeIndex === index ? 0 : -1}
                onClick={() => handleItemClick(item)}
                className={`block w-full px-4 py-2 text-left text-sm
                            text-gray-700 focus:outline-none dark:text-gray-200
                            ${
                              activeIndex === index
                                ? 'bg-blue-500 text-white'
                                : 'hover:bg-gray-100 dark:hover:bg-gray-700'
                            }`}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

## 4. Navigation Bar (with skip link)

```jsx
// components/Navbar.jsx
import { DropdownMenu } from './DropdownMenu';

export function Navbar() {
  const productItems = [
    { id: 'analytics', label: 'Analytics', onSelect: () => console.log('Analytics') },
    { id: 'engagement', label: 'Engagement', onSelect: () => console.log('Engagement') },
    { id: 'security', label: 'Security', onSelect: () => console.log('Security') },
    { id: 'integrations', label: 'Integrations', onSelect: () => console.log('Integrations') },
  ];

  return (
    <>
      {/* Skip link for keyboard/screen-reader users */}
      <a
        href="#main-content"
        className="sr-only rounded bg-blue-600 px-4 py-2 text-white
                   focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50"
      >
        Skip to main content
      </a>

      <nav
        aria-label="Main navigation"
        className="flex items-center gap-4 border-b border-gray-200 bg-white px-6
                   py-3 dark:border-gray-700 dark:bg-gray-900"
      >
        <a
          href="/"
          className="text-lg font-bold text-gray-900 focus:outline-none
                     focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-white"
        >
          Logo
        </a>

        <div className="ml-auto flex items-center gap-2">
          <DropdownMenu label="Products" items={productItems} />
          <a
            href="/pricing"
            className="rounded-md px-3 py-2 text-sm font-medium text-gray-700
                       hover:bg-gray-100 focus:outline-none focus-visible:ring-2
                       focus-visible:ring-blue-500 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            Pricing
          </a>
        </div>
      </nav>
    </>
  );
}
```

## 5. Example Usage

```jsx
// App.jsx
import { useState } from 'react';
import { Navbar } from './components/Navbar';
import { Modal } from './components/Modal';

export default function App() {
  const [isModalOpen, setIsModalOpen] = useState(false);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <Navbar />

      <main id="main-content" className="p-8">
        <h1 className="mb-4 text-2xl font-bold text-gray-900 dark:text-white">
          Accessible Components Demo
        </h1>

        <button
          type="button"
          onClick={() => setIsModalOpen(true)}
          className="rounded-md bg-blue-600 px-4 py-2 text-white
                     hover:bg-blue-700 focus:outline-none focus-visible:ring-2
                     focus-visible:ring-blue-500 focus-visible:ring-offset-2"
        >
          Open Modal
        </button>

        <Modal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          title="Confirm Action"
        >
          <p className="mb-4">
            This modal traps focus, closes on Escape, restores focus to the
            trigger, and locks body scroll.
          </p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setIsModalOpen(false)}
              className="rounded-md px-4 py-2 text-gray-700 hover:bg-gray-100
                         focus:outline-none focus-visible:ring-2
                         focus-visible:ring-blue-500 dark:text-gray-200
                         dark:hover:bg-gray-700"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => setIsModalOpen(false)}
              className="rounded-md bg-blue-600 px-4 py-2 text-white
                         hover:bg-blue-700 focus:outline-none focus-visible:ring-2
                         focus-visible:ring-blue-500"
            >
              Confirm
            </button>
          </div>
        </Modal>
      </main>
    </div>
  );
}
```

## Accessibility Features Summary

### Dropdown Menu
| Feature | Implementation |
|---------|---------------|
| **ARIA roles** | `aria-haspopup="menu"`, `aria-expanded`, `role="menu"`, `role="menuitem"` |
| **Keyboard** | `↓`/`↑` navigate, `Enter`/`Space` open, `Home`/`End` jump, `Esc` close, `Tab` close |
| **Roving tabindex** | Only active item has `tabIndex={0}`; others `-1` |
| **Type-ahead** | Type a letter to jump to matching item |
| **Focus return** | Focus returns to trigger button on close |
| **Click outside** | Closes menu without stealing focus |

### Modal
| Feature | Implementation |
|---------|---------------|
| **ARIA roles** | `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, `aria-describedby` |
| **Focus trap** | `useFocusTrap` cycles Tab within dialog |
| **Focus restore** | Returns focus to the element that opened it |
| **Escape to close** | Global keydown listener |
| **Scroll lock** | Sets `body.overflow = hidden` while open |
| **Portal** | Rendered to `document.body` to avoid stacking/overflow issues |

## Recommended Tailwind Config

Ensure the `sr-only` / `not-sr-only` utilities and `focus-visible` work:

```js
// tailwind.config.js
module.exports = {
  darkMode: 'class',
  content: ['./src/**/*.{js,jsx,ts,tsx}'],
  theme: { extend: {} },
  plugins: [],
};
```

**Key notes for further hardening:**
- Consider using [`inert`](https://developer.mozilla.org/en-US/docs/Web/API/HTMLElement/inert) on background content when the modal is open for even stronger screen-reader isolation.
- For complex apps, libraries like **Radix UI** or **Headless UI** implement these patterns following the [WAI-ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/) — this code mirrors those specs but is dependency-free.
- Always test with real screen readers (VoiceOver, NVDA) and keyboard-only navigation.

Would you like me to add a **multi-level/nested submenu**, a **mobile hamburger version**, or convert these to **TypeScript**?
</details>
