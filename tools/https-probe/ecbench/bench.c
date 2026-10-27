#include <stdio.h>
#include <string.h>
#include "mbedtls/ecdsa.h"
#include "mbedtls/ecdh.h"
static unsigned s = 12345;
static int rng(void *p, unsigned char *b, size_t n) { (void)p; while (n--) { s = s * 1103515245u + 12345u; *b++ = s >> 16; } return 0; }
int main(int argc, char **argv) {
    int which = argc > 1 ? argv[1][0] - '0' : 0;
    mbedtls_ecp_group g; mbedtls_mpi d, z, r, sg; mbedtls_ecp_point Q, Qp;
    mbedtls_ecp_group_init(&g); mbedtls_mpi_init(&d); mbedtls_mpi_init(&z); mbedtls_mpi_init(&r); mbedtls_mpi_init(&sg);
    mbedtls_ecp_point_init(&Q); mbedtls_ecp_point_init(&Qp);
    mbedtls_ecp_group_load(&g, MBEDTLS_ECP_DP_SECP256R1);
    unsigned char h[32]; memset(h, 7, 32);
    int ret = 0;
    // setup: the server's long-term key and a client's ephemeral public key
    ret |= mbedtls_ecp_gen_keypair(&g, &d, &Q, rng, NULL);
    mbedtls_mpi d2; mbedtls_mpi_init(&d2); ret |= mbedtls_ecp_gen_keypair(&g, &d2, &Qp, rng, NULL);
    if (which == 0) { puts("setup only"); return ret; }
    mbedtls_mpi e; mbedtls_ecp_point E; mbedtls_mpi_init(&e); mbedtls_ecp_point_init(&E);
    // 1: ECDHE keygen (server ephemeral)   2: + ECDSA sign of ServerKeyExchange   3: + ECDH shared secret
    ret |= mbedtls_ecdh_gen_public(&g, &e, &E, rng, NULL);
    if (which >= 2) ret |= mbedtls_ecdsa_sign(&g, &r, &sg, &d, h, 32, rng, NULL);
    if (which >= 3) ret |= mbedtls_ecdh_compute_shared(&g, &z, &Qp, &e, rng, NULL);
    printf("which=%d ret=%d\n", which, ret);
    return ret;
}
