// The rp2 port's mbedTLS config (ports/rp2/mbedtls/mbedtls_config_port.h, MicroPython
// v1.29.0) rebuilt for the unix port, so the heap a TLS server connection takes can be
// measured on a PC: bare-metal allocation (mbedTLS buffers come from the MicroPython GC
// heap, as on the Pico), same options, same mbedTLS 3.6.6. Only differences: entropy from
// the OS instead of the RP2040 ROSC, and the time hook.
#ifndef MICROPY_INCLUDED_MBEDTLS_CONFIG_H
#define MICROPY_INCLUDED_MBEDTLS_CONFIG_H
#define MBEDTLS_ECP_NIST_OPTIM
#define MBEDTLS_CIPHER_MODE_CTR
#define MBEDTLS_TIMING_C
#define MICROPY_MBEDTLS_CONFIG_BARE_METAL (1)
#include "extmod/mbedtls/mbedtls_config_common.h"
// Variant: the firmware change proposed in REPORT.md (receive buffer 16 KB -> 4 KB).
#undef MBEDTLS_SSL_IN_CONTENT_LEN
#define MBEDTLS_SSL_IN_CONTENT_LEN (4096)
#undef MBEDTLS_ENTROPY_HARDWARE_ALT
#undef MBEDTLS_NO_PLATFORM_ENTROPY
#endif
