"""Small, self-contained R2-D2 hologram overlay for Windows."""

from __future__ import annotations

import queue
import textwrap
import threading


class HologramOverlay:
    """A transparent, always-on-top Tk window shown while Jarvis is active."""

    WIDTH = 400
    HEIGHT = 730
    _KEY = "#010203"

    def __init__(self) -> None:
        self._commands: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="JarvisHologram", daemon=True)
        self._thread.start()

    def show(self) -> None:
        self._commands.put(("show", ""))

    def hide(self) -> None:
        self._commands.put(("hide", ""))

    def set_question(self, text: str) -> None:
        self._commands.put(("question", text))

    def set_answer(self, text: str) -> None:
        self._commands.put(("answer", text))

    def close(self) -> None:
        self._commands.put(("close", ""))

    def _run(self) -> None:
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.configure(bg=self._KEY)
            try:
                root.wm_attributes("-transparentcolor", self._KEY)
            except tk.TclError:
                root.attributes("-alpha", 0.92)

            screen_w = root.winfo_screenwidth()
            screen_h = root.winfo_screenheight()
            x = max(0, screen_w - self.WIDTH - 30)
            y = max(0, screen_h - self.HEIGHT - 75)
            root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

            canvas = tk.Canvas(
                root, width=self.WIDTH, height=self.HEIGHT,
                bg=self._KEY, highlightthickness=0, bd=0,
            )
            canvas.pack()
            scanline, question_text, answer_text = self._draw(canvas)
            scan_y = [100]

            def poll() -> None:
                try:
                    while True:
                        command, value = self._commands.get_nowait()
                        if command == "show":
                            canvas.itemconfigure(question_text, text="Listening for your question...")
                            canvas.itemconfigure(answer_text, text="Awaiting response...")
                            root.deiconify()
                            root.lift()
                        elif command == "hide":
                            root.withdraw()
                        elif command == "question":
                            canvas.itemconfigure(question_text, text=self._format_text(value))
                        elif command == "answer":
                            canvas.itemconfigure(answer_text, text=self._format_text(value))
                        elif command == "close":
                            root.destroy()
                            return
                except queue.Empty:
                    pass

                scan_y[0] = 100 + (scan_y[0] - 99) % 315
                canvas.coords(scanline, 76, scan_y[0], 324, scan_y[0])
                root.after(65, poll)

            root.after(65, poll)
            root.mainloop()
        except Exception:  # noqa: BLE001 - the optional visual must not break voice control
            pass

    @staticmethod
    def _format_text(text: str) -> str:
        text = " ".join(text.split())
        if len(text) > 126:
            text = text[:123].rstrip() + "..."
        return "\n".join(textwrap.wrap(text, width=43, break_long_words=True)[:3])

    @staticmethod
    def _draw(canvas):
        """Draw a neon-blue, technical illustration of the familiar astromech."""
        glow = "#075bb5"
        blue = "#078be8"
        cyan = "#34dcff"
        pale = "#a8f5ff"

        def line(points, color=cyan, width=2, smooth=False):
            return canvas.create_line(
                *points, fill=color, width=width, smooth=smooth,
                capstyle="round", joinstyle="round",
            )

        def oval(box, color=cyan, width=2, fill=""):
            return canvas.create_oval(*box, outline=color, width=width, fill=fill)

        def poly(points, color=cyan, width=2, fill=""):
            return canvas.create_polygon(
                *points, outline=color, width=width, fill=fill,
                joinstyle="round",
            )

        # Holographic pedestal and projection beam.
        for box, color, width in [
            ((82, 423, 318, 468), glow, 8),
            ((88, 428, 312, 462), blue, 3),
            ((101, 434, 299, 455), cyan, 1),
        ]:
            oval(box, color, width)
        line([104, 438, 112, 184], glow, 1)
        line([296, 438, 288, 184], glow, 1)
        line([102, 438, 298, 438], cyan, 2)

        # Feet, ankles and characteristic side legs.
        poly([112, 306, 83, 320, 69, 391, 98, 402, 131, 365], glow, 8)
        poly([112, 306, 83, 320, 69, 391, 98, 402, 131, 365], cyan, 2)
        poly([288, 306, 317, 320, 331, 391, 302, 402, 269, 365], glow, 8)
        poly([288, 306, 317, 320, 331, 391, 302, 402, 269, 365], cyan, 2)
        poly([65, 388, 101, 396, 119, 413, 73, 410], blue, 3)
        poly([335, 388, 299, 396, 281, 413, 327, 410], blue, 3)
        line([80, 399, 108, 404, 114, 411], pale, 1)
        line([320, 399, 292, 404, 286, 411], pale, 1)
        for x in (91, 309):
            oval((x - 9, 332, x + 9, 350), cyan, 2)
            line([x, 352, x, 382], blue, 3)
            line([x - 6, 369, x + 6, 369], pale, 1)

        # Barrel-shaped body with its blue side panels.
        poly([117, 215, 283, 215, 296, 321, 277, 365, 123, 365, 104, 321], glow, 9)
        poly([117, 215, 283, 215, 296, 321, 277, 365, 123, 365, 104, 321], cyan, 2)
        oval((117, 204, 283, 238), blue, 3)
        line([113, 254, 287, 254], cyan, 2)
        line([109, 329, 291, 329], blue, 3)
        # Front access panels and tiny status lights.
        poly([139, 245, 192, 245, 190, 314, 136, 314], blue, 2)
        poly([208, 243, 263, 245, 267, 312, 211, 313], blue, 2)
        line([145, 256, 184, 256], pale, 2)
        line([145, 264, 179, 264], cyan, 1)
        for yy in (276, 287, 298):
            oval((146, yy, 153, yy + 7), pale, 1, fill=blue)
            line([160, yy + 3, 181, yy + 3], cyan, 1)
        oval((220, 254, 251, 285), cyan, 2)
        oval((226, 260, 245, 279), blue, 2)
        oval((231, 265, 240, 274), pale, 1, fill=cyan)
        for yy in (294, 303):
            line([220, yy, 256, yy], cyan, 2)
        # Small shoulder details.
        for x in (119, 281):
            oval((x - 8, 222, x + 8, 246), cyan, 2)
            line([x, 233, x, 310], blue, 2)

        # Domed head, split band and R2-D2's iconic optical eye.
        poly([117, 164, 121, 128, 139, 99, 167, 79, 200, 72,
              233, 79, 261, 99, 279, 128, 283, 164], glow, 10)
        poly([117, 164, 121, 128, 139, 99, 167, 79, 200, 72,
              233, 79, 261, 99, 279, 128, 283, 164], cyan, 2)
        line([118, 164, 282, 164], pale, 2)
        line([125, 151, 275, 151], blue, 3)
        # Dome's left and right panels.
        poly([133, 122, 159, 102, 165, 147, 128, 151], blue, 2)
        poly([168, 96, 194, 88, 194, 146, 169, 146], cyan, 1)
        poly([207, 88, 232, 96, 231, 146, 207, 146], blue, 2)
        poly([240, 102, 266, 122, 271, 151, 235, 147], cyan, 1)
        for x in (140, 151, 178, 186, 216, 224, 250, 260):
            oval((x - 2, 112 + (x % 3), x + 2, 116 + (x % 3)), pale, 1, fill=cyan)
        # Main eye lens and secondary indicator.
        oval((205, 112, 246, 153), glow, 7)
        oval((205, 112, 246, 153), pale, 2)
        oval((212, 119, 239, 146), blue, 3)
        oval((220, 127, 231, 138), pale, 1, fill=cyan)
        oval((158, 125, 174, 141), cyan, 2)
        oval((163, 130, 169, 136), pale, 1, fill=cyan)
        # Antenna and head-side brackets.
        line([198, 74, 198, 55, 203, 48], pale, 2)
        oval((199, 43, 208, 52), cyan, 2)
        line([117, 140, 105, 148, 104, 198], blue, 3)
        line([283, 140, 295, 148, 296, 198], blue, 3)
        oval((100, 191, 108, 201), pale, 1, fill=blue)
        oval((292, 191, 300, 201), pale, 1, fill=blue)

        # Compact HUD labels and framing marks.
        canvas.create_text(200, 20, text="R2-D2  /  HOLOGRAM", fill=cyan,
                           font=("Consolas", 10, "bold"))
        # Query/answer panel below the projected droid.
        canvas.create_rectangle(28, 479, 372, 686, outline=blue, width=1)
        line([38, 500, 362, 500], glow, 1)
        canvas.create_text(43, 490, text="QUESTION", fill=cyan,
                           anchor="w", font=("Consolas", 9, "bold"))
        question_text = canvas.create_text(
            43, 508, text="Listening for your question...", fill=pale,
            anchor="nw", width=314, font=("Consolas", 10),
        )
        line([38, 570, 362, 570], glow, 1)
        canvas.create_text(43, 559, text="R2-D2  /  RESPONSE", fill=cyan,
                           anchor="w", font=("Consolas", 9, "bold"))
        answer_text = canvas.create_text(
            43, 578, text="Awaiting response...", fill=pale,
            anchor="nw", width=314, font=("Consolas", 10),
        )
        canvas.create_text(200, 710, text="●  SYSTEM ONLINE  •  LISTENING",
                           fill=pale, font=("Consolas", 9, "bold"))
        for x, direction in ((45, 1), (355, -1)):
            line([x, 92, x + 14 * direction, 92, x + 14 * direction, 117], blue, 2)
            line([x, 385, x + 14 * direction, 385, x + 14 * direction, 360], blue, 2)
        scanline = canvas.create_line(76, 100, 324, 100, fill=pale, width=1)
        return scanline, question_text, answer_text
