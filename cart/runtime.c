/* Cartridge runtime for the Golden Sun merged cartridge (code placed in free ROM space).
 *
 * gs1_clear_to_link_buffer(): what Golden Sun 1's "Send (cable)" would transmit, read straight from the
 * GS1 save bank: the first 0x1004 bytes of the RAM image of the newest "clear data" save.
 *
 * GS1 save layout (flash bank 1, 16 sectors of 4 KiB):
 *   +0x000 "CAMELOT"   +0x007 slot id   +0x008 u16 checksum   +0x00A u16 counter   +0x010 data[0xFF0]
 *   Slot n (0..2) holds RAM 0x02000000..+0xFF0, slot n+3 holds RAM 0x02001000..+0xFF0.
 *   Clear data is marked by RAM byte 0x0200044F == 1.
 */
#include "profile.h"   /* generated per language version by tools/transfer_patch.py */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define FLASH ((volatile u8 *)0x0E000000)
#define SECTOR_SIZE 0x1000
#define HEADER_SIZE 0x10
#define DATA_SIZE 0xFF0
#define LINK_SIZE 0x1004
#define CLEAR_MARK_OFFSET PROFILE_GS1_CLEAR_MARKER
#define CLEAR_SLOT 6            /* dedicated clear-data slot of the merged cart (second half: 9) */

static void flash_cmd(u8 cmd)
{
    FLASH[0x5555] = 0xAA;
    FLASH[0x2AAA] = 0x55;
    FLASH[0x5555] = cmd;
}

static void flash_bank(u8 bank)
{
    flash_cmd(0xB0);
    FLASH[0] = bank;
}

static u8 rd8(u32 off) { return FLASH[off]; }
static u16 rd16(u32 off) { return (u16)(rd8(off) | (rd8(off + 1) << 8)); }

static int is_camelot(u32 sec)
{
    static const char magic[7] = {'C', 'A', 'M', 'E', 'L', 'O', 'T'};
    for (int i = 0; i < 7; i++)
        if (rd8(sec + i) != (u8)magic[i])
            return 0;
    return 1;
}

/* Newest sector holding `slot` (optionally requiring the clear marker). Returns sector offset or -1. */
static int find_slot(int slot, int need_clear, u16 *counter_out)
{
    int best = -1;
    u16 best_counter = 0;
    for (int s = 0; s < 16; s++) {
        u32 sec = (u32)s * SECTOR_SIZE;
        if (!is_camelot(sec) || rd8(sec + 7) != slot)
            continue;
        if (need_clear && rd8(sec + HEADER_SIZE + CLEAR_MARK_OFFSET) != 1)
            continue;
        u16 c = rd16(sec + 0xA);
        if (best < 0 || c > best_counter) {
            best = (int)sec;
            best_counter = c;
        }
    }
    if (counter_out)
        *counter_out = best_counter;
    return best;
}

static int first_slot_is_normal(int sec) { return rd8((u32)sec + 7) != CLEAR_SLOT; }

/* Locate the newest GS1 clear save: first half (slot n) and second half (slot n+3). Bank 1 must be selected. */
static int find_clear(int *first_out, int *second_out)
{
    static const u8 firsts[4] = {CLEAR_SLOT, 0, 1, 2};
    int first = -1, second = -1;
    u16 best = 0;
    for (int k = 0; k < 4; k++) {
        int n = firsts[k];
        u16 c;
        int sec = find_slot(n, 1, &c);
        if (sec < 0)
            continue;
        int sec2 = find_slot(n + 3, 0, 0);
        if (sec2 < 0)
            continue;
        if (first < 0 || (n != CLEAR_SLOT && first_slot_is_normal(first) && c > best)) {
            first = sec;
            second = sec2;
            best = c;
        }
    }
    *first_out = first;
    *second_out = second;
    return first >= 0;
}

/* 1 if a GS1 clear save exists. Leaves flash on bank 0 (TLA). */
int gs1_clear_available(void)
{
    int a, b;
    flash_bank(1);
    int found = find_clear(&a, &b);
    flash_bank(0);
    return found;
}

/* Returns 1 and fills dst[0x1004] if a GS1 clear save exists, else 0. Leaves flash on bank 0 (TLA). */
int gs1_clear_to_link_buffer(u8 *dst)
{
    int first, second;
    flash_bank(1);
    int found = find_clear(&first, &second);
    if (found) {
        for (u32 i = 0; i < DATA_SIZE; i++)
            dst[i] = rd8((u32)first + HEADER_SIZE + i);
        for (u32 i = DATA_SIZE; i < 0x1000; i++)
            dst[i] = 0;
        for (u32 i = 0x1000; i < LINK_SIZE; i++)
            dst[i] = rd8((u32)second + HEADER_SIZE + (i - 0x1000));
    }
    flash_bank(0);
    return found;
}

/* Called from TLA's patched link-receive function: fill TLA's receive buffer. */
int tla_receive_gs1(void)
{
    return gs1_clear_to_link_buffer((u8 *)PROFILE_TLA_RECV_BUFFER);
}

/* ---------------------------------------------------------------------------------------------------------
 * Chapter transition: end of Golden Sun 1 -> new game of The Lost Age.
 * ------------------------------------------------------------------------------------------------------- */
#define REG_DISPCNT (*(volatile u16 *)0x04000000)
#define REG_VCOUNT (*(volatile u16 *)0x04000006)
#define REG_KEYINPUT (*(volatile u16 *)0x04000130)
#define REG_IME (*(volatile u16 *)0x04000208)
#define VRAM ((volatile u32 *)0x06000000)
#define CHAPTER_CARD ((const u32 *)0x09B10000)  /* 240x160 BGR555 image placed by the builder */
#define MAILBOX (*(volatile u32 *)0x0203FFF0)   /* survives TLA's start-up until its title code runs */
#define MAILBOX_NEW_GAME 0x32534D47u             /* "GMS2": start TLA's new game directly */
#define TLA_ENTRY PROFILE_TLA_ENTRY

typedef int (*fn0)(void);
typedef int (*fn2)(int, void *);
#define GS1_FN(addr) ((addr) + 0x01000000 + 1)   /* GS1 is relocated by +16 MiB; Thumb entry */

static void wait_vblank(void)
{
    while (REG_VCOUNT >= 160) {}
    while (REG_VCOUNT < 160) {}
}

static __attribute__((noreturn)) void boot_tla_new_game(void)
{
    REG_IME = 0;
    REG_DISPCNT = 0x0080;                       /* forced blank */
    for (u32 i = 0; i < 240 * 160 / 2; i++)
        VRAM[i] = CHAPTER_CARD[i];
    REG_DISPCNT = 0x0403;                       /* mode 3, BG2 */
    for (int f = 0; f < 240; f++) {             /* ~4 s, or A / START */
        wait_vblank();
        if (f > 30 && (~REG_KEYINPUT & 0x0009))
            break;
    }
    REG_DISPCNT = 0x0080;
    flash_bank(1);                              /* emulators: switch to the 128 KiB chip */
    flash_bank(0);                              /* TLA owns bank 0 */
    __asm__ volatile("movs r0, #0xFF\n\tsvc #1" ::: "r0", "r1", "r2", "r3", "memory");  /* RegisterRamReset */
    MAILBOX = MAILBOX_NEW_GAME;
    __asm__ volatile("bx %0" :: "r"(TLA_ENTRY));   /* ARM entry of The Lost Age */
    __builtin_unreachable();
}

/* Called from GS1's title code when the game was cleared (instead of "Save your adventure?").
 * Saves the clear data to the dedicated slot with GS1's own routines, then starts chapter 2. */
void gs1_chapter_end(void)
{
    *(volatile u8 *)(0x02000000 + CLEAR_MARK_OFFSET) = 1;             /* clear marker, as GS1 sets before saving clear data */
    flash_bank(1);                              /* GS1's bank (normally already selected; savestates reset it) */
    if (((fn0)GS1_FN(PROFILE_GS1_FN_FLASH_SCAN))() == 0) {     /* flash scan / init */
        ((fn0)GS1_FN(PROFILE_GS1_FN_SAVE_INIT))();
        *(volatile u16 *)PROFILE_GS1_SLOT_VAR = CLEAR_SLOT;
        ((fn0)GS1_FN(PROFILE_GS1_FN_PREPARE))();            /* prepare save data */
        ((fn0)GS1_FN(PROFILE_GS1_FN_ACTORS))();            /* store actor positions */
        ((fn2)GS1_FN(PROFILE_GS1_FN_WRITE_SLOT))(CLEAR_SLOT, (void *)0x02000000);
        ((fn2)GS1_FN(PROFILE_GS1_FN_WRITE_SLOT))(CLEAR_SLOT + 3, (void *)0x02001000);
    }
    boot_tla_new_game();
}

/* Called from TLA's title code instead of its title menu: 0 = New Game when chapter 2 was requested. */
int tla_title_menu_override(void)
{
    if (MAILBOX == MAILBOX_NEW_GAME) {
        MAILBOX = 0;
        return 1;
    }
    return 0;
}

/* ---------------------------------------------------------------------------------------------------------
 * Start menu (runs at power-on, before either game).
 * Mode 0: BG2 = 8bpp panorama (GS1 title scene -> TLA title scene) that pans slowly back and forth; only 32
 * tile columns are in VRAM, new columns are streamed in at the edge. OBJ = Golden Sun logo (8 sprites 64x64,
 * 8bpp). BG0 = game-style menu window (4bpp, palette bank 15). All data is placed by bootmenu.menu_data().
 * ------------------------------------------------------------------------------------------------------- */
#define MENU_DATA 0x09B30000u                    /* header of u32 offsets, see bootmenu.menu_data() */
#define INTRO_DATA 0x09C00000u                   /* GS1 intro replay, see intro_timeline.assemble() */
#define GS1_ENTRY 0x09000000                     /* ARM entry (GS1's own header branch, PC-relative) */
#define REG_BG0CNT (*(volatile u16 *)0x04000008)
#define REG_BG2CNT (*(volatile u16 *)0x0400000C)
#define REG_BG2HOFS (*(volatile u16 *)0x04000018)
#define REG_BLDCNT (*(volatile u16 *)0x04000050)
#define REG_BLDY (*(volatile u16 *)0x04000054)
#define VRAM16 ((volatile u16 *)0x06000000)
#define OAM16 ((volatile u16 *)0x07000000)
#define PANO_MAP 0xA000                          /* VRAM offsets */
#define WIN_MAP 0xA800
#define WIN_TILES 0xC000
#define LOGO_TILES 0x10000
#define COL_BYTES (20 * 64)                      /* one 8 px wide column of the panorama, 20 8bpp tiles */
#define PAN_VMAX 85                              /* top speed in 1/256 px per frame (~1/3 px) */
#define PAN_ACC 1                                /* speed change per frame: ~1.4 s to start / stop */
#define PAN_HOLD 150                             /* frames to rest at either end */
#define PAN_FIRST_HOLD 60                        /* rest after the intro before the first pan */

enum { H_COLUMNS, H_PANO_PAL, H_PANO_TILES, H_LOGO_PAL, H_LOGO_TILES, H_WIN_TILES, H_WIN_STATE_BYTES, H_WIN_ROW,
       H_WIN_ROWS };
enum { GAME_GS1, GAME_TLA };

static void fast_copy(const void *src, u32 vram_off, u32 bytes)   /* BIOS CpuFastSet, bytes % 32 == 0 */
{
    register const void *r0 __asm__("r0") = src;
    register u32 r1 __asm__("r1") = 0x06000000 + vram_off;
    register u32 r2 __asm__("r2") = bytes / 4;
    __asm__ volatile("svc #0x0C" : "+r"(r0), "+r"(r1), "+r"(r2) :: "r3", "memory");
}

static const u8 *menu_part(int field) { return (const u8 *)(MENU_DATA + ((const u32 *)MENU_DATA)[field]); }

static int has_normal_save(int bank)
{
    int found = 0;
    flash_bank(bank);
    for (int s = 0; s < 16 && !found; s++) {
        u32 sec = (u32)s * SECTOR_SIZE;
        if (is_camelot(sec) && rd8(sec + 7) < 3 && rd8(sec + HEADER_SIZE + CLEAR_MARK_OFFSET) != 1)
            found = 1;
    }
    return found;
}

static void load_column(int x)
{
    if (x >= 0 && x < (int)((const u32 *)MENU_DATA)[H_COLUMNS])
        fast_copy(menu_part(H_PANO_TILES) + (u32)x * COL_BYTES, (u32)(x & 31) * COL_BYTES, COL_BYTES);
}

static void show_window(int state)
{
    u32 n = ((const u32 *)MENU_DATA)[H_WIN_STATE_BYTES];
    fast_copy(menu_part(H_WIN_TILES) + (u32)state * n, WIN_TILES + 32, n);
}

static void menu_setup(void)
{
    const u32 *h = (const u32 *)MENU_DATA;
    REG_DISPCNT = 0x0080;                                         /* forced blank while loading */
    for (u32 i = 0; i < 0x200; i++)                               /* BG + OBJ palettes */
        ((volatile u16 *)0x05000000)[i] = ((const u16 *)menu_part(H_PANO_PAL))[i & 0xFF];
    for (u32 i = 0; i < 0x100; i++)
        ((volatile u16 *)0x05000200)[i] = ((const u16 *)menu_part(H_LOGO_PAL))[i];
    for (u32 r = 0; r < 32; r++)
        for (u32 c = 0; c < 32; c++) {
            VRAM16[(PANO_MAP >> 1) + r * 32 + c] = (u16)(r < 20 ? c * 20 + r : 0);
            u32 wr = r - h[H_WIN_ROW];
            VRAM16[(WIN_MAP >> 1) + r * 32 + c] =
                (u16)(wr < h[H_WIN_ROWS] && c < 30 ? (1 + wr * 30 + c) | 0xF000 : 0);
        }
    for (u32 i = 0; i < 16; i++)                                  /* window tile 0 = transparent */
        VRAM16[(WIN_TILES >> 1) + i] = 0;
    for (int x = 0; x < 32; x++)
        load_column(x);
    fast_copy(menu_part(H_LOGO_TILES), LOGO_TILES, 0x8000);
    for (u32 i = 0; i < 128; i++)
        OAM16[i * 4] = 0x0200;                                    /* hide all sprites */
    for (u32 k = 0; k < 8; k++) {                                 /* logo: 4x2 sprites 64x64, 8bpp, priority 1 */
        OAM16[k * 4 + 0] = (u16)(0x2000 | (k / 4) * 64);
        OAM16[k * 4 + 1] = (u16)(0xC000 | (k % 4) * 64);
        OAM16[k * 4 + 2] = (u16)(0x0400 | k * 128);
    }
    REG_BG2CNT = 0x1482;                                          /* prio 2, chars 0, 8bpp, map 20, 256x256 */
    REG_BG0CNT = 0x150C;                                          /* prio 0, chars 3, 4bpp, map 21 */
    for (u32 i = 0; i < 8; i++)                                  /* all BG scroll offsets (the intro */
        ((volatile u16 *)0x04000010)[i] = 0;                     /* leaves BG1/BG2 scrolled vertically) */
    REG_BLDCNT = 0x00BF;                                          /* fade from white (after the intro flash) */
    REG_BLDY = 16;
}

/* GS1's own sound engine (MusicPlayer2000) plays its intro music on the start screen. No interrupts are used:
 * VSync (restart the sound DMA) right after vblank starts, Main (mixing) once per frame. */
typedef void (*fnv)(void);
typedef void (*fnu)(unsigned);
static void sound_vsync(void) { ((fnv)GS1_FN(PROFILE_GS1_M4A_VSYNC))(); }
static void sound_main(void) { ((fnv)GS1_FN(PROFILE_GS1_M4A_MAIN))(); }

static void sound_start(void)
{
    {                                           /* GS1's IWRAM code (division helpers the engine calls), as GS1's */
        register u32 r0 __asm__("r0") = PROFILE_GS1_IWRAM_SRC + 0x01000000;   /* start-up copies it; no IRQs */
        register u32 r1 __asm__("r1") = 0x03000000;
        register u32 r2 __asm__("r2") = PROFILE_GS1_IWRAM_BYTES / 4;
        __asm__ volatile("svc #0x0C" : "+r"(r0), "+r"(r1), "+r"(r2) :: "r3", "memory");
    }
    ((fnv)GS1_FN(PROFILE_GS1_M4A_INIT))();
    ((fnu)GS1_FN(PROFILE_GS1_M4A_SONG_START))(PROFILE_GS1_INTRO_SONG);
}

static void sound_stop(void)
{
    *(volatile u16 *)0x040000C6 = 0;            /* DMA1, DMA2 (sound FIFOs), timer 0, master enable */
    *(volatile u16 *)0x040000D2 = 0;
    *(volatile u16 *)0x04000102 = 0;
    *(volatile u16 *)0x04000084 = 0;
}

static void frame_start(void)                  /* wait for vblank, then keep the music running */
{
    wait_vblank();
    sound_vsync();
}

/* Replays Golden Sun's intro (camera gliding up Mt. Aleph) from the op stream built by intro_timeline.py.
 * One frame of ops is applied right after each vblank starts. A / START skips. */
enum { OP_FRAME, OP_COPY, OP_DATA, OP_REG, OP_FADE, OP_END };

static void intro_play(void)
{
    const u32 *h = (const u32 *)INTRO_DATA;
    const u32 *op = (const u32 *)(INTRO_DATA + h[0]);
    const u16 *base = (const u16 *)(INTRO_DATA + h[1]);
    REG_DISPCNT = 0x0080;
    {
        u32 zero = 0;
        register const void *r0 __asm__("r0") = &zero;            /* CpuFastSet fill: VRAM, palette, OAM */
        register u32 r1 __asm__("r1") = 0x06000000;
        register u32 r2 __asm__("r2") = (0x18000 / 4) | (1u << 24);
        __asm__ volatile("svc #0x0C" : "+r"(r0), "+r"(r1), "+r"(r2) :: "r3", "memory");
    }
    for (u32 i = 0; i < 0x200; i++)
        ((volatile u16 *)0x05000000)[i] = 0;
    for (u32 i = 0; i < 128; i++)
        OAM16[i * 4] = 0x0200;
    sound_start();
    for (int f = 0; f < PROFILE_GS1_INTRO_SONG_LEAD; f++) {    /* music starts before the picture */
        frame_start();
        sound_main();
    }
    u16 prev = (u16)~REG_KEYINPUT;
    for (;;) {
        frame_start();
        for (;;) {
            u32 code = op[0] & 0xFF, n = op[0] >> 8, dst = op[1];
            if (code == OP_END)
                return;
            if (code == OP_FRAME) { op += 3; break; }
            if (code == OP_COPY) {
                register const void *r0 __asm__("r0") = (const void *)(INTRO_DATA + op[2]);
                register u32 r1 __asm__("r1") = dst;
                register u32 r2 __asm__("r2") = n / 4;
                __asm__ volatile("svc #0x0C" : "+r"(r0), "+r"(r1), "+r"(r2) :: "r3", "memory");
                op += 3;
            } else if (code == OP_DATA) {
                const u16 *d = (const u16 *)(op + 2);
                for (u32 i = 0; i < n / 2; i++)
                    ((volatile u16 *)dst)[i] = d[i];
                op += 2 + n / 4;
            } else if (code == OP_REG) {
                *(volatile u16 *)dst = (u16)op[2];
                op += 3;
            } else {                                              /* OP_FADE: (2,0,0) -> palette, k / 256 */
                int k = (int)op[2];
                for (u32 i = 0; i < 0x200; i++) {
                    int c = base[i], r = c & 31, g = (c >> 5) & 31, b = (c >> 10) & 31;
                    r = 2 + (((r - 2) * k) >> 8);
                    g = (g * k) >> 8;
                    b = (b * k) >> 8;
                    ((volatile u16 *)0x05000000)[i] = (u16)(r | g << 5 | b << 10);
                }
                op += 3;
            }
        }
        sound_main();
        u16 held = (u16)~REG_KEYINPUT;
        if (held & (u16)~prev & 0x0009)                           /* A / START: skip */
            return;
        prev = held;
    }
}

static __attribute__((noreturn)) void boot_game(int game)
{
    REG_BLDCNT = 0x00FF;                                          /* fade to black */
    for (int k = 0; k <= 16; k++) {
        frame_start();
        REG_BLDY = (u16)k;
        sound_main();
    }
    sound_stop();
    REG_DISPCNT = 0x0080;
    REG_BLDCNT = 0;
    REG_BLDY = 0;
    flash_bank(1);                               /* emulators: switch to the 128 KiB chip */
    flash_bank(game == GAME_GS1 ? 1 : 0);        /* each game owns one 64 KiB bank */
    __asm__ volatile("movs r0, #0xFF\n\tsvc #1" ::: "r0", "r1", "r2", "r3", "memory");  /* RegisterRamReset */
    __asm__ volatile("bx %0" :: "r"(game == GAME_GS1 ? GS1_ENTRY : TLA_ENTRY));
    __builtin_unreachable();
}

/* Window states: 0..2 = menu with Continue (cursor on 0..2), 3..4 = without Continue (cursor on 0..1). */
void boot_main(void)
{
    REG_IME = 0;
    int tla_save = has_normal_save(0);
    int gs1_save = has_normal_save(1);
    int with_continue = tla_save || gs1_save;
    int count = with_continue ? 3 : 2;
    int base = with_continue ? 0 : 3;
    int sel = 0;
    int pmax = (int)((const u32 *)MENU_DATA)[H_COLUMNS] * 8 - 240;
    int posq = 0, vel = 0, dir = 1, hold = PAN_FIRST_HOLD, lo = 0, fade = 16 * 2;

    intro_play();
    *(volatile u16 *)0x04000048 = 0x3636;        /* windows: same layers + effects on, then fade to white */
    REG_BLDCNT = 0x00BF;
    for (int k = 2; k <= 16; k += 2) {
        frame_start();
        REG_BLDY = (u16)k;
        sound_main();
    }
    frame_start();
    REG_DISPCNT = 0x0080;                        /* white (forced blank) while the menu loads */
    REG_BLDCNT = 0;
    menu_setup();
    sound_main();
    show_window(base + sel);
    REG_DISPCNT = 0x1540;                        /* mode 0, BG0 + BG2 + OBJ, 1D sprite tiles */
    u16 prev = (u16)~REG_KEYINPUT;
    for (;;) {
        frame_start();
        if (fade > 0)
            REG_BLDY = (u16)(--fade / 2);
        if (hold > 0)
            hold--;
        else {                                   /* eased pan: accelerate, cruise, brake before the end */
            int target = dir > 0 ? pmax << 8 : 0;
            int dist = dir > 0 ? target - posq : posq;
            if (((vel * vel) >> 1) >= dist)
                vel = vel > PAN_ACC ? vel - PAN_ACC : PAN_ACC;
            else if (vel < PAN_VMAX)
                vel += PAN_ACC;
            posq += dir * vel;
            if (dir > 0 ? posq >= target : posq <= 0) {
                posq = target;
                vel = 0;
                dir = -dir;
                hold = PAN_HOLD;
            }
        }
        int pos = posq >> 8;
        int x0 = pos >> 3;                       /* keep columns x0 .. x0+30 loaded (ring of 32) */
        while (x0 > lo + 1) { load_column(lo + 32); lo++; }
        while (x0 < lo) { lo--; load_column(lo); }
        REG_BG2HOFS = (u16)pos;
        sound_main();

        u16 held = (u16)~REG_KEYINPUT;
        u16 pressed = held & (u16)~prev;
        prev = held;
        if (pressed & 0x0040) sel = (sel + count - 1) % count;          /* up */
        else if (pressed & 0x0080) sel = (sel + 1) % count;             /* down */
        else if (pressed & 0x0009) break;                               /* A / START */
        else continue;
        show_window(base + sel);
    }
    int game;
    if (with_continue && sel == 0)
        game = tla_save ? GAME_TLA : GAME_GS1;
    else
        game = (sel == count - 2) ? GAME_GS1 : GAME_TLA;
    boot_game(game);
}
