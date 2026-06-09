#include "proto/tv_stretch_proto.h"
#include "unity.h"

TEST_CASE("protocol version is 1", "[protocol]")
{
    TEST_ASSERT_EQUAL_INT(1, TVS_PROTO_VER);
}

TEST_CASE("message type enum values are sequential", "[protocol]")
{
    TEST_ASSERT_EQUAL_INT(0, TVS_MSG_HELLO);
    TEST_ASSERT_EQUAL_INT(1, TVS_MSG_HEARTBEAT);
    TEST_ASSERT_EQUAL_INT(2, TVS_MSG_ACK);
    TEST_ASSERT_EQUAL_INT(3, TVS_MSG_EVENT);
    TEST_ASSERT_EQUAL_INT(4, TVS_MSG_COMMAND_BATCH);
}

TEST_CASE("tvs_command_t struct sizes are reasonable", "[protocol]")
{
    tvs_command_t cmd = {0};
    TEST_ASSERT_EQUAL_UINT(sizeof(cmd.batch_id), 48);
    TEST_ASSERT_EQUAL_UINT(sizeof(cmd.cmd), 32);
    TEST_ASSERT_EQUAL_UINT(sizeof(cmd.payload_json), 256);
}
