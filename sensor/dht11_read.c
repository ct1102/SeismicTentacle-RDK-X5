/*
 * dht11_read.c - Read DHT11 via libgpiod on RDK X5
 * Pin 7 (BOARD) = gpiochip3 line 9 (global GPIO 420)
 * Compile: gcc -o dht11_read dht11_read.c -lgpiod
 * Usage:   ./dht11_read         (正常输出 JSON)
 *          ./dht11_read --debug (打印每位脉宽)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <gpiod.h>

#define CHIP_NAME   "gpiochip3"
#define LINE_OFFSET 9

static long ns_diff(struct timespec *a, struct timespec *b) {
    return (b->tv_sec - a->tv_sec) * 1000000000L + (b->tv_nsec - a->tv_nsec);
}

/* 等待引脚变为 target，返回空或超时 */
static int wait_for(struct gpiod_line *line, int target, long timeout_ns) {
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    while (gpiod_line_get_value(line) != target) {
        clock_gettime(CLOCK_MONOTONIC, &t1);
        if (ns_diff(&t0, &t1) > timeout_ns) return -1;
    }
    return 0;
}

int main(int argc, char **argv) {
    struct gpiod_chip *chip;
    struct gpiod_line *line;
    struct timespec t0, t1;
    int i, bits[40];
    int debug = (argc > 1 && strcmp(argv[1], "--debug") == 0);

    chip = gpiod_chip_open_by_name(CHIP_NAME);
    if (!chip) { perror("chip_open"); return 1; }
    line = gpiod_chip_get_line(chip, LINE_OFFSET);
    if (!line) { perror("get_line"); gpiod_chip_close(chip); return 1; }

    /* ── 发送启动信号 ── */
    gpiod_line_request_output(line, "dht11", 0);
    gpiod_line_set_value(line, 0);
    usleep(20000);
    gpiod_line_set_value(line, 1);
    gpiod_line_release(line);

    /* ── 等待 DHT11 响应 ── */
    gpiod_line_request_input(line, "dht11");

    /* 响应 LOW ~80μs */
    if (wait_for(line, 0, 1000000) < 0) {
        fprintf(stderr, "E: timeout response LOW\n"); goto fail; }
    if (wait_for(line, 1, 1000000) < 0) {
        fprintf(stderr, "E: timeout response HIGH\n"); goto fail; }
    if (wait_for(line, 0, 1000000) < 0) {
        fprintf(stderr, "E: timeout bit0 start LOW\n"); goto fail; }

    /* ── 读 40 位 ──
     * 每位：LOW ~50μs → HIGH 26μs(0)/70μs(1) → LOW ~50μs
     * 我们：等到 HIGH 开始计时 → 等到 LOW 结束 = HIGH宽度
     */
    for (i = 0; i < 40; i++) {
        if (wait_for(line, 1, 300000) < 0) {
            fprintf(stderr, "E: timeout bit%d HIGH rise\n", i); goto fail; }
        clock_gettime(CLOCK_MONOTONIC, &t0);
        if (wait_for(line, 0, 300000) < 0) {
            fprintf(stderr, "E: timeout bit%d HIGH fall\n", i); goto fail; }
        clock_gettime(CLOCK_MONOTONIC, &t1);
        long high_ns = ns_diff(&t0, &t1);
        bits[i] = (high_ns > 40000) ? 1 : 0;
        if (debug) fprintf(stderr, "bit%2d: %5ld ns → %d\n", i, high_ns, bits[i]);
    }

    /* ── 解析 5 字节 ── */
    int h_i = 0, h_d = 0, t_i = 0, t_d = 0, chk = 0;
    for (i = 0; i < 8; i++)  h_i = (h_i << 1) | bits[i];
    for (i = 8; i < 16; i++) h_d = (h_d << 1) | bits[i];
    for (i = 16; i < 24; i++) t_i = (t_i << 1) | bits[i];
    for (i = 24; i < 32; i++) t_d = (t_d << 1) | bits[i];
    for (i = 32; i < 40; i++) chk = (chk << 1) | bits[i];

    if (debug) {
        fprintf(stderr, "h_i=%d h_d=%d t_i=%d t_d=%d chk=%d calc=%d\n",
                h_i, h_d, t_i, t_d, chk, (h_i + h_d + t_i + t_d) & 0xFF);
    }

    if (((h_i + h_d + t_i + t_d) & 0xFF) != chk) {
        fprintf(stderr, "E: checksum mismatch\n");
        goto fail;
    }

    printf("{\"temp\": %d, \"hum\": %d}\n", t_i, h_i);
    gpiod_line_release(line);
    gpiod_chip_close(chip);
    return 0;

fail:
    printf("{\"temp\": null, \"hum\": null}\n");
    gpiod_line_release(line);
    gpiod_chip_close(chip);
    return 1;
}
