/**
 * Unit tests for the InputBox component.
 *
 * Coverage:
 * - Rendering: textarea, send/stop button, placeholder text
 * - Send/interrupt: button click dispatches correct callback based on streaming state
 * - Keyboard: Enter sends, Shift+Enter does not send
 * - Empty input: prevents sending blank/whitespace-only messages
 * - Text clearing: input is cleared after successful send
 * - @mention detection: typing triggers onSearchFiles, dropdown appears
 * - Mention dropdown: navigation (ArrowUp/Down), selection (Enter/Tab/click), dismiss (Escape)
 * - Attachment badges: render and remove
 * - Image previews: render and remove
 * - Image paste: ClipboardEvent with image item calls onAddImage via FileReader
 *
 * Total: 28 tests across 7 describe blocks
 */
import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InputBox } from "../components/InputBox";
import type { FileAttachment, ImageAttachment } from "../types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Default props that satisfy InputBoxProps with no-op callbacks. */
function defaultProps(overrides: Partial<Parameters<typeof InputBox>[0]> = {}) {
  return {
    isStreaming: false,
    attachments: [] as FileAttachment[],
    images: [] as ImageAttachment[],
    mentionResults: [] as Array<{ path: string; name: string; relativePath: string }>,
    onSend: vi.fn(),
    onInterrupt: vi.fn(),
    onAddAttachment: vi.fn(),
    onRemoveAttachment: vi.fn(),
    onAddImage: vi.fn(),
    onRemoveImage: vi.fn(),
    onSearchFiles: vi.fn(),
    postMessage: vi.fn(),
    ...overrides,
  };
}

// ============================================================================
// Rendering
// ============================================================================

describe("InputBox -- Rendering", () => {
  test("renders a textarea with the expected placeholder", () => {
    render(<InputBox {...defaultProps()} />);
    const textarea = screen.getByPlaceholderText("Ask ClarAIty...");
    expect(textarea).toBeInTheDocument();
    expect(textarea.tagName).toBe("TEXTAREA");
  });

  test('renders Send button when not streaming', () => {
    render(<InputBox {...defaultProps({ isStreaming: false })} />);
    const btn = screen.getByRole("button", { name: "Send" });
    expect(btn).toBeInTheDocument();
    expect(btn).not.toHaveClass("streaming");
  });

  test('renders Stop button when streaming', () => {
    render(<InputBox {...defaultProps({ isStreaming: true })} />);
    const btn = screen.getByRole("button", { name: "Stop" });
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveClass("streaming");
  });
});

// ============================================================================
// Send / Interrupt
// ============================================================================

describe("InputBox -- Send and Interrupt", () => {
  test("clicking Send calls onSend with trimmed text", async () => {
    const onSend = vi.fn();
    render(<InputBox {...defaultProps({ onSend })} />);

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "  Hello agent  " } });

    const sendBtn = screen.getByRole("button", { name: "Send" });
    fireEvent.click(sendBtn);

    expect(onSend).toHaveBeenCalledOnce();
    expect(onSend).toHaveBeenCalledWith("Hello agent");
  });

  test("clicking Stop calls onInterrupt instead of onSend", () => {
    const onSend = vi.fn();
    const onInterrupt = vi.fn();
    render(<InputBox {...defaultProps({ isStreaming: true, onSend, onInterrupt })} />);

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "some text" } });

    const stopBtn = screen.getByRole("button", { name: "Stop" });
    fireEvent.click(stopBtn);

    expect(onInterrupt).toHaveBeenCalledOnce();
    expect(onSend).not.toHaveBeenCalled();
  });

  test("empty input does not trigger onSend", () => {
    const onSend = vi.fn();
    render(<InputBox {...defaultProps({ onSend })} />);

    const sendBtn = screen.getByRole("button", { name: "Send" });
    fireEvent.click(sendBtn);

    expect(onSend).not.toHaveBeenCalled();
  });

  test("whitespace-only input does not trigger onSend", () => {
    const onSend = vi.fn();
    render(<InputBox {...defaultProps({ onSend })} />);

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "   \n  " } });

    const sendBtn = screen.getByRole("button", { name: "Send" });
    fireEvent.click(sendBtn);

    expect(onSend).not.toHaveBeenCalled();
  });

  test("text is cleared after a successful send", () => {
    const onSend = vi.fn();
    render(<InputBox {...defaultProps({ onSend })} />);

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hello" } });
    expect(textarea.value).toBe("Hello");

    const sendBtn = screen.getByRole("button", { name: "Send" });
    fireEvent.click(sendBtn);

    expect(textarea.value).toBe("");
  });
});

// ============================================================================
// Keyboard Shortcuts
// ============================================================================

describe("InputBox -- Keyboard shortcuts", () => {
  test("Enter key sends message", () => {
    const onSend = vi.fn();
    render(<InputBox {...defaultProps({ onSend })} />);

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "via enter" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    expect(onSend).toHaveBeenCalledOnce();
    expect(onSend).toHaveBeenCalledWith("via enter");
  });

  test("Shift+Enter does NOT send message", () => {
    const onSend = vi.fn();
    render(<InputBox {...defaultProps({ onSend })} />);

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "multiline" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });

    expect(onSend).not.toHaveBeenCalled();
  });

  test("Enter key while streaming calls onInterrupt", () => {
    const onInterrupt = vi.fn();
    const onSend = vi.fn();
    render(
      <InputBox {...defaultProps({ isStreaming: true, onSend, onInterrupt })} />,
    );

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "stop" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    expect(onInterrupt).toHaveBeenCalledOnce();
    expect(onSend).not.toHaveBeenCalled();
  });
});

// ============================================================================
// @Mention Detection
// ============================================================================

describe("InputBox -- @mention detection", () => {
  test("typing @src calls onSearchFiles with the query", () => {
    const onSearchFiles = vi.fn();
    render(<InputBox {...defaultProps({ onSearchFiles })} />);

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "look at @src" } });

    expect(onSearchFiles).toHaveBeenCalledOnce();
    expect(onSearchFiles).toHaveBeenCalledWith("src");
  });

  test("typing @ alone triggers onSearchFiles with empty query", () => {
    const onSearchFiles = vi.fn();
    render(<InputBox {...defaultProps({ onSearchFiles })} />);

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "hello @" } });

    expect(onSearchFiles).toHaveBeenCalledWith("");
  });

  test("text without @ does not call onSearchFiles", () => {
    const onSearchFiles = vi.fn();
    render(<InputBox {...defaultProps({ onSearchFiles })} />);

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "just a normal message" } });

    expect(onSearchFiles).not.toHaveBeenCalled();
  });
});

// ============================================================================
// Mention Dropdown
// ============================================================================

describe("InputBox -- Mention dropdown", () => {
  const mentionFiles = [
    { path: "/src/app.ts", name: "app.ts", relativePath: "src/app.ts" },
    { path: "/src/utils.ts", name: "utils.ts", relativePath: "src/utils.ts" },
    { path: "/src/types.ts", name: "types.ts", relativePath: "src/types.ts" },
  ];

  test("dropdown is visible when showMentions is active and results exist", () => {
    render(
      <InputBox {...defaultProps({ mentionResults: mentionFiles })} />,
    );

    const textarea = screen.getByRole("textbox");
    // Trigger @mention to set showMentions = true
    fireEvent.change(textarea, { target: { value: "@src" } });

    const dropdown = document.querySelector(".mention-dropdown");
    expect(dropdown).toHaveClass("visible");

    const items = document.querySelectorAll(".mention-item");
    expect(items).toHaveLength(3);
  });

  test("dropdown is hidden when no mention is active", () => {
    render(
      <InputBox {...defaultProps({ mentionResults: mentionFiles })} />,
    );

    // No @mention typed -- dropdown should not be visible
    const dropdown = document.querySelector(".mention-dropdown");
    expect(dropdown).not.toHaveClass("visible");
  });

  test("clicking a mention item inserts it into the text", () => {
    render(
      <InputBox {...defaultProps({ mentionResults: mentionFiles })} />,
    );

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "check @src" } });

    // Click the second mention item (utils.ts)
    const items = document.querySelectorAll(".mention-item");
    fireEvent.click(items[1]);

    // Should replace @src with @src/utils.ts followed by a space
    expect(textarea.value).toBe("check @src/utils.ts ");
  });

  test("first mention item is selected by default", () => {
    render(
      <InputBox {...defaultProps({ mentionResults: mentionFiles })} />,
    );

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "@app" } });

    const items = document.querySelectorAll(".mention-item");
    expect(items[0]).toHaveClass("selected");
    expect(items[1]).not.toHaveClass("selected");
  });

  test("ArrowDown moves selection down in dropdown", () => {
    render(
      <InputBox {...defaultProps({ mentionResults: mentionFiles })} />,
    );

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "@app" } });

    // Move down once
    fireEvent.keyDown(textarea, { key: "ArrowDown" });

    const items = document.querySelectorAll(".mention-item");
    expect(items[0]).not.toHaveClass("selected");
    expect(items[1]).toHaveClass("selected");
  });

  test("ArrowUp moves selection up in dropdown", () => {
    render(
      <InputBox {...defaultProps({ mentionResults: mentionFiles })} />,
    );

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "@app" } });

    // Move down then up to get back to first item
    fireEvent.keyDown(textarea, { key: "ArrowDown" });
    fireEvent.keyDown(textarea, { key: "ArrowDown" });
    fireEvent.keyDown(textarea, { key: "ArrowUp" });

    const items = document.querySelectorAll(".mention-item");
    expect(items[1]).toHaveClass("selected");
  });

  test("ArrowDown does not go past last item", () => {
    render(
      <InputBox {...defaultProps({ mentionResults: mentionFiles })} />,
    );

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "@app" } });

    // Press ArrowDown more times than there are items
    fireEvent.keyDown(textarea, { key: "ArrowDown" });
    fireEvent.keyDown(textarea, { key: "ArrowDown" });
    fireEvent.keyDown(textarea, { key: "ArrowDown" });
    fireEvent.keyDown(textarea, { key: "ArrowDown" });

    const items = document.querySelectorAll(".mention-item");
    expect(items[2]).toHaveClass("selected"); // last item (index 2)
  });

  test("Enter key selects the highlighted mention item", () => {
    render(
      <InputBox {...defaultProps({ mentionResults: mentionFiles })} />,
    );

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "see @app" } });

    // Select second item then press Enter
    fireEvent.keyDown(textarea, { key: "ArrowDown" });
    fireEvent.keyDown(textarea, { key: "Enter" });

    expect(textarea.value).toBe("see @src/utils.ts ");
  });

  test("Tab key selects the highlighted mention item", () => {
    render(
      <InputBox {...defaultProps({ mentionResults: mentionFiles })} />,
    );

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "see @app" } });

    // Default is first item, press Tab to select it
    fireEvent.keyDown(textarea, { key: "Tab" });

    expect(textarea.value).toBe("see @src/app.ts ");
  });

  test("Escape key hides the mention dropdown", () => {
    render(
      <InputBox {...defaultProps({ mentionResults: mentionFiles })} />,
    );

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "@app" } });

    // Dropdown should be visible
    let dropdown = document.querySelector(".mention-dropdown");
    expect(dropdown).toHaveClass("visible");

    // Press Escape
    fireEvent.keyDown(textarea, { key: "Escape" });

    // Dropdown should no longer be visible
    dropdown = document.querySelector(".mention-dropdown");
    expect(dropdown).not.toHaveClass("visible");
  });

  test("mention dropdown displays file name and relative path", () => {
    render(
      <InputBox {...defaultProps({ mentionResults: mentionFiles })} />,
    );

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "@app" } });

    expect(screen.getByText("app.ts")).toBeInTheDocument();
    expect(screen.getByText("src/app.ts")).toBeInTheDocument();
    expect(screen.getByText("utils.ts")).toBeInTheDocument();
    expect(screen.getByText("src/utils.ts")).toBeInTheDocument();
  });
});

// ============================================================================
// Attachment Badges
// ============================================================================

describe("InputBox -- Attachment badges", () => {
  test("renders attachment badges when attachments are present", () => {
    const attachments: FileAttachment[] = [
      { path: "/src/main.py", name: "main.py" },
      { path: "/src/utils.py", name: "utils.py" },
    ];
    render(<InputBox {...defaultProps({ attachments })} />);

    expect(screen.getByText("main.py")).toBeInTheDocument();
    expect(screen.getByText("utils.py")).toBeInTheDocument();
  });

  test("does not render attachment bar when no attachments", () => {
    render(<InputBox {...defaultProps({ attachments: [] })} />);
    const attachmentBar = document.querySelector(".attachment-bar");
    expect(attachmentBar).toBeNull();
  });

  test("clicking remove button on attachment calls onRemoveAttachment with index", () => {
    const onRemoveAttachment = vi.fn();
    const attachments: FileAttachment[] = [
      { path: "/a.py", name: "a.py" },
      { path: "/b.py", name: "b.py" },
    ];
    render(<InputBox {...defaultProps({ attachments, onRemoveAttachment })} />);

    // Each badge has an "x" span as remove button
    const badges = document.querySelectorAll(".attachment-badge");
    const removeBtn = within(badges[1] as HTMLElement).getByText("x");
    fireEvent.click(removeBtn);

    expect(onRemoveAttachment).toHaveBeenCalledOnce();
    expect(onRemoveAttachment).toHaveBeenCalledWith(1);
  });

  test("attachment badge has title with full path", () => {
    const attachments: FileAttachment[] = [
      { path: "/src/components/Header.tsx", name: "Header.tsx" },
    ];
    render(<InputBox {...defaultProps({ attachments })} />);

    const badge = document.querySelector(".attachment-badge");
    expect(badge).toHaveAttribute("title", "/src/components/Header.tsx");
  });
});

// ============================================================================
// Image Previews
// ============================================================================

describe("InputBox -- Image previews", () => {
  const sampleImages: ImageAttachment[] = [
    { data: "data:image/png;base64,abc", mimeType: "image/png", name: "screenshot.png" },
    { data: "data:image/jpeg;base64,xyz", mimeType: "image/jpeg", name: "photo.jpg" },
  ];

  test("renders image previews when images are present", () => {
    render(<InputBox {...defaultProps({ images: sampleImages })} />);

    const imgs = screen.getAllByRole("img");
    expect(imgs).toHaveLength(2);
    expect(imgs[0]).toHaveAttribute("src", "data:image/png;base64,abc");
    expect(imgs[0]).toHaveAttribute("alt", "screenshot.png");
    expect(imgs[1]).toHaveAttribute("src", "data:image/jpeg;base64,xyz");
    expect(imgs[1]).toHaveAttribute("alt", "photo.jpg");
  });

  test("does not render image preview bar when no images", () => {
    render(<InputBox {...defaultProps({ images: [] })} />);
    const bar = document.querySelector(".image-preview-bar");
    expect(bar).toBeNull();
  });

  test("image without name uses 'image' as alt text", () => {
    const images: ImageAttachment[] = [
      { data: "data:image/png;base64,abc", mimeType: "image/png" },
    ];
    render(<InputBox {...defaultProps({ images })} />);

    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("alt", "image");
  });

  test("clicking remove button on image calls onRemoveImage with index", () => {
    const onRemoveImage = vi.fn();
    render(
      <InputBox {...defaultProps({ images: sampleImages, onRemoveImage })} />,
    );

    const removeButtons = document.querySelectorAll(".remove-img");
    fireEvent.click(removeButtons[0]);

    expect(onRemoveImage).toHaveBeenCalledOnce();
    expect(onRemoveImage).toHaveBeenCalledWith(0);
  });

  test("clicking second image remove button passes correct index", () => {
    const onRemoveImage = vi.fn();
    render(
      <InputBox {...defaultProps({ images: sampleImages, onRemoveImage })} />,
    );

    const removeButtons = document.querySelectorAll(".remove-img");
    fireEvent.click(removeButtons[1]);

    expect(onRemoveImage).toHaveBeenCalledWith(1);
  });
});

// ============================================================================
// Image Paste Handling
// ============================================================================

describe("InputBox -- Image paste", () => {
  test("pasting an image file calls onAddImage after FileReader completes", async () => {
    const onAddImage = vi.fn();
    render(<InputBox {...defaultProps({ onAddImage })} />);

    // Mock a File object
    const fakeFile = new File(["imagedata"], "pasted.png", { type: "image/png" });
    Object.defineProperty(fakeFile, "size", { value: 1024 }); // 1KB

    // Mock FileReader
    const mockReadAsDataURL = vi.fn();
    let onloadCallback: (() => void) | null = null;
    const mockResult = "data:image/png;base64,fakedata";

    vi.spyOn(globalThis, "FileReader").mockImplementation(() => {
      const reader = {
        readAsDataURL: mockReadAsDataURL,
        result: mockResult,
        set onload(cb: (() => void) | null) {
          onloadCallback = cb;
        },
        get onload() {
          return onloadCallback;
        },
      } as unknown as FileReader;
      // When readAsDataURL is called, trigger onload synchronously
      mockReadAsDataURL.mockImplementation(() => {
        if (onloadCallback) onloadCallback();
      });
      return reader;
    });

    // Create a clipboard event with an image item
    const clipboardData = {
      items: [
        {
          type: "image/png",
          getAsFile: () => fakeFile,
        },
      ],
    };

    const textarea = screen.getByRole("textbox");
    fireEvent.paste(textarea, { clipboardData });

    expect(mockReadAsDataURL).toHaveBeenCalledWith(fakeFile);
    expect(onAddImage).toHaveBeenCalledOnce();
    expect(onAddImage).toHaveBeenCalledWith({
      data: "data:image/png;base64,fakedata",
      mimeType: "image/png",
      name: "pasted.png",
    });

    vi.restoreAllMocks();
  });

  test("pasting a non-image item does not call onAddImage", () => {
    const onAddImage = vi.fn();
    render(<InputBox {...defaultProps({ onAddImage })} />);

    const clipboardData = {
      items: [
        {
          type: "text/plain",
          getAsFile: () => null,
        },
      ],
    };

    const textarea = screen.getByRole("textbox");
    fireEvent.paste(textarea, { clipboardData });

    expect(onAddImage).not.toHaveBeenCalled();
  });

  test("pasting image when already at MAX_IMAGES (5) does not call onAddImage", () => {
    const onAddImage = vi.fn();
    const existingImages: ImageAttachment[] = Array.from({ length: 5 }, (_, i) => ({
      data: `data:image/png;base64,img${i}`,
      mimeType: "image/png",
      name: `image${i}.png`,
    }));
    render(<InputBox {...defaultProps({ images: existingImages, onAddImage })} />);

    const fakeFile = new File(["data"], "extra.png", { type: "image/png" });
    const clipboardData = {
      items: [
        {
          type: "image/png",
          getAsFile: () => fakeFile,
        },
      ],
    };

    const textarea = screen.getByRole("textbox");
    fireEvent.paste(textarea, { clipboardData });

    expect(onAddImage).not.toHaveBeenCalled();
  });

  test("pasting oversized image (>10MB) does not call onAddImage", () => {
    const onAddImage = vi.fn();
    render(<InputBox {...defaultProps({ onAddImage })} />);

    const fakeFile = new File(["data"], "huge.png", { type: "image/png" });
    Object.defineProperty(fakeFile, "size", { value: 11 * 1024 * 1024 }); // 11MB

    const clipboardData = {
      items: [
        {
          type: "image/png",
          getAsFile: () => fakeFile,
        },
      ],
    };

    const textarea = screen.getByRole("textbox");
    fireEvent.paste(textarea, { clipboardData });

    expect(onAddImage).not.toHaveBeenCalled();
  });
});
