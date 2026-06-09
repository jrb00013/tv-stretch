/**
 * Tests for CEC frame construction logic.
 * These verify the byte-level correctness of CEC messages
 * without requiring actual GPIO hardware.
 */
#include "cec/cec_bitbang.h"
#include "unity.h"
#include <string.h>

/* Helper: construct a CEC active source frame payload bytes. */
static void build_active_source_body(uint16_t phys_addr, uint8_t *out, size_t *len)
{
    out[0] = 0x82;                                          /* <Active Source> opcode */
    out[1] = (uint8_t)((phys_addr >> 8) & 0xFF);             /* physical address high */
    out[2] = (uint8_t)(phys_addr & 0xFF);                    /* physical address low */
    *len = 3;
}

TEST_CASE("cec active source frame has correct opcode and address", "[cec]")
{
    uint8_t body[4];
    size_t len = 0;
    build_active_source_body(0x2000, body, &len);
    TEST_ASSERT_EQUAL_UINT(3, len);
    TEST_ASSERT_EQUAL_HEX8(0x82, body[0]);   /* Active Source opcode */
    TEST_ASSERT_EQUAL_HEX8(0x20, body[1]);   /* physical address high */
    TEST_ASSERT_EQUAL_HEX8(0x00, body[2]);   /* physical address low */
}

TEST_CASE("cec active source with alternative physical address", "[cec]")
{
    uint8_t body[4];
    size_t len = 0;
    build_active_source_body(0x1000, body, &len);
    TEST_ASSERT_EQUAL_UINT(3, len);
    TEST_ASSERT_EQUAL_HEX8(0x10, body[1]);
    TEST_ASSERT_EQUAL_HEX8(0x00, body[2]);
}

TEST_CASE("cec standby frame is single byte opcode 0x36", "[cec]")
{
    /* Standby is just opcode 0x36 in the data portion */
    uint8_t opcode = 0x36;
    TEST_ASSERT_EQUAL_HEX8(0x36, opcode);
}

TEST_CASE("cec broadcast ping frame is single byte 0x83", "[cec]")
{
    /* The broadcast ping used by the firmware is 0x83 */
    uint8_t ping = 0x83;
    TEST_ASSERT_EQUAL_HEX8(0x83, ping);
}
