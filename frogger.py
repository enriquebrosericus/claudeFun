#!/usr/bin/env python3
"""Frogger, lazy edition. Arrow keys to cross the road. stdlib tkinter only."""
import sys, os, random, tkinter as tk

CELL, COLS, ROWS = 40, 13, 13
W, H = COLS * CELL, ROWS * CELL
SAFE = {0, 6, 12}  # goal, median, start

# lane: row -> (direction, speed px/frame, car length in cells)
LANES = {r: (1 if r % 2 else -1, random.uniform(1.5, 4.0), random.choice((2, 3)))
         for r in range(ROWS) if r not in SAFE}


def overlap(ax, aw, bx, bw):
    return not (ax + aw <= bx or bx + bw <= ax)


def collides(frog_col, frog_row, cars):
    """True if frog cell overlaps any car in its row. The whole game in one check."""
    fx, fw = frog_col * CELL, CELL
    for row, x, length in cars:
        if row == frog_row and overlap(fx, fw, x, length * CELL):
            return True
    return False


class Frogger:
    def __init__(self, root):
        self.c = tk.Canvas(root, width=W, height=H, bg="#111")
        self.c.pack()
        root.bind("<Up>", lambda e: self.move(0, -1))
        root.bind("<Down>", lambda e: self.move(0, 1))
        root.bind("<Left>", lambda e: self.move(-1, 0))
        root.bind("<Right>", lambda e: self.move(1, 0))
        self.reset_game()
        self.tick()

    def reset_game(self):
        self.lives, self.score, self.over = 3, 0, False
        # cars: list of [row, x_float, length] spread across each lane
        self.cars = []
        for row in LANES:
            for i in range(random.randint(2, 3)):
                self.cars.append([row, random.uniform(0, W), LANES[row][2]])
        self.reset_frog()

    def reset_frog(self):
        self.fc, self.fr = COLS // 2, ROWS - 1

    def move(self, dc, dr):
        if self.over:
            return self.reset_game()
        self.fc = max(0, min(COLS - 1, self.fc + dc))
        self.fr = max(0, min(ROWS - 1, self.fr + dr))
        if self.fr == 0:  # reached the top
            self.score += 1
            self.reset_frog()

    def tick(self):
        if not self.over:
            for car in self.cars:
                row, x, length = car
                d, speed, _ = LANES[row]
                x += d * speed
                if x > W:
                    x = -length * CELL
                elif x + length * CELL < 0:
                    x = W
                car[1] = x
            if collides(self.fc, self.fr, self.cars):
                self.lives -= 1
                self.reset_frog()
                if self.lives <= 0:
                    self.over = True
        self.draw()
        self.c.update_idletasks()  # ponytail: macOS Tk won't flush the canvas otherwise -> white window
        self.c.after(16, self.tick)

    def draw(self):
        c = self.c
        c.delete("all")
        for r in range(ROWS):
            color = "#1b5e20" if r in SAFE else "#333"
            c.create_rectangle(0, r * CELL, W, (r + 1) * CELL, fill=color, outline="")
        for row, x, length in self.cars:
            c.create_rectangle(x, row * CELL + 5, x + length * CELL, (row + 1) * CELL - 5,
                               fill="#e53935", outline="")
        c.create_oval(self.fc * CELL + 4, self.fr * CELL + 4,
                      (self.fc + 1) * CELL - 4, (self.fr + 1) * CELL - 4,
                      fill="#43a047", outline="white")
        c.create_text(50, 12, fill="white", text=f"Lives {self.lives}")
        c.create_text(W - 50, 12, fill="white", text=f"Score {self.score}")
        if self.over:
            c.create_text(W // 2, H // 2, fill="yellow", font=("", 24),
                          text="GAME OVER\npress any arrow")


def _selfcheck():
    assert overlap(0, 40, 20, 40) and not overlap(0, 40, 40, 40)
    assert collides(1, 5, [[5, 40, 1]]) and not collides(1, 5, [[5, 200, 1]])
    print("ok")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _selfcheck()
    else:
        root = tk.Tk()
        root.title("Frogger")
        Frogger(root)
        if sys.platform == "darwin":
            # ponytail: a detached python isn't activated as an app, so the OS never
            # paints the Tk window (stays white). Activate ourselves by PID.
            os.system('osascript -e \'tell application "System Events" to set '
                      'frontmost of (first process whose unix id is %d) to true\' '
                      '>/dev/null 2>&1 &' % os.getpid())
        try:                     # ponytail: cosmetic first-paint/raise; skip if Tk session is flaky
            root.update()        # macOS Tk paints white otherwise
            root.lift()
            root.focus_force()
        except tk.TclError:
            pass
        root.mainloop()
