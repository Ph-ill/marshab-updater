// Linked into the unix TLS probe build with -Wl,--wrap=m_tracked_calloc,--wrap=m_tracked_free:
// counts the bytes mbedTLS holds on the MicroPython heap (current and peak, +8 B per block
// for the tracked-alloc header). SIGUSR1 prints "ALLOC cur=<B> peak=<B> live=<n>" to stderr
// and resets the peak to the current value, so peak-cur around one connection = its cost.
#include <stddef.h>
#include <stdint.h>
#include <signal.h>
#include <stdio.h>
#include <unistd.h>
void *__real_m_tracked_calloc(size_t nmemb, size_t size);
void __real_m_tracked_free(void *ptr);
#define SLOTS 8192
static void *keys[SLOTS];
static size_t vals[SLOTS];
static size_t cur, peak, live;
static unsigned h(void *p) { return ((uintptr_t)p >> 3) * 2654435761u % SLOTS; }
void *__wrap_m_tracked_calloc(size_t nmemb, size_t size) {
    void *p = __real_m_tracked_calloc(nmemb, size);
    if (p) {
        size_t n = nmemb * size + 8;   // + the tracked-alloc node header (two pointers, 32-bit)
        unsigned i = h(p);
        while (keys[i]) i = (i + 1) % SLOTS;
        keys[i] = p; vals[i] = n; cur += n; live++;
        if (cur > peak) peak = cur;
    }
    return p;
}
void __wrap_m_tracked_free(void *p) {
    if (p) {
        unsigned i = h(p), k = 0;
        while (keys[i] != p && k++ < SLOTS) i = (i + 1) % SLOTS;
        if (keys[i] == p) {
            cur -= vals[i]; live--; keys[i] = 0;
            // re-insert the rest of the cluster (open addressing delete)
            unsigned j = (i + 1) % SLOTS;
            while (keys[j]) { void *kk = keys[j]; size_t vv = vals[j]; keys[j] = 0;
                unsigned t = h(kk); while (keys[t]) t = (t + 1) % SLOTS; keys[t] = kk; vals[t] = vv;
                j = (j + 1) % SLOTS; }
        }
    }
    __real_m_tracked_free(p);
}
static void on_usr1(int s) {
    (void)s;
    char b[96];
    int n = snprintf(b, sizeof b, "ALLOC cur=%u peak=%u live=%u\n", (unsigned)cur, (unsigned)peak, (unsigned)live);
    write(2, b, n);
    peak = cur;
}
__attribute__((constructor)) static void init(void) { signal(SIGUSR1, on_usr1); }
