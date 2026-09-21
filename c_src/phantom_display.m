#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <AppKit/AppKit.h>
#import <signal.h>
#import <sys/stat.h>

#pragma mark - Private CoreGraphics Virtual Display Interfaces

@interface CGVirtualDisplayMode : NSObject
- (instancetype)initWithWidth:(uint32_t)width height:(uint32_t)height refreshRate:(double)refreshRate;
@end

@interface CGVirtualDisplaySettings : NSObject
@property(nonatomic, strong) NSArray *modes;
@property(nonatomic, assign) uint32_t hiDPI;
@property(nonatomic, assign) uint32_t rotation;
@end

@interface CGVirtualDisplayDescriptor : NSObject
@property(nonatomic, strong) dispatch_queue_t queue;
@property(nonatomic, copy) NSString *name;
@property(nonatomic, assign) CGSize sizeInMillimeters;
@property(nonatomic, assign) uint32_t maxPixelsWide;
@property(nonatomic, assign) uint32_t maxPixelsHigh;
@property(nonatomic, assign) uint32_t serialNum;
@property(nonatomic, assign) uint32_t productID;
@property(nonatomic, assign) uint32_t vendorID;
@property(nonatomic, assign) CGPoint redPrimary;
@property(nonatomic, assign) CGPoint greenPrimary;
@property(nonatomic, assign) CGPoint bluePrimary;
@property(nonatomic, assign) CGPoint whitePoint;
@property(nonatomic, copy) void (^terminationHandler)(id a, id b);
@end

@interface CGVirtualDisplay : NSObject
- (instancetype)initWithDescriptor:(CGVirtualDisplayDescriptor *)descriptor;
- (BOOL)applySettings:(CGVirtualDisplaySettings *)settings;
@property(readonly, nonatomic) CGDirectDisplayID displayID;
@end

static volatile sig_atomic_t g_running = 1;

static void handle_signal(int sig) {
    (void)sig;
    g_running = 0;
}

static NSString *get_state_file_path(void) {
    const char *envPath = getenv("PHANTOM_STATE_PATH");
    if (envPath && strlen(envPath) > 0) {
        return [NSString stringWithUTF8String:envPath];
    }
    NSString *homeDir = NSHomeDirectory();
    return [homeDir stringByAppendingPathComponent:@".cache/phantom_workstation/display_state.json"];
}

int run_daemon(uint32_t width, uint32_t height) {
    signal(SIGTERM, handle_signal);
    signal(SIGINT, handle_signal);

    NSString *statePath = get_state_file_path();
    NSString *stateDir = [statePath stringByDeletingLastPathComponent];
    [[NSFileManager defaultManager] createDirectoryAtPath:stateDir
                              withIntermediateDirectories:YES
                                               attributes:nil
                                                    error:nil];

    CGVirtualDisplayDescriptor *desc = [[CGVirtualDisplayDescriptor alloc] init];
    desc.queue = dispatch_queue_create("org.phantom.workstation.queue", DISPATCH_QUEUE_SERIAL);
    desc.name = @"Phantom-Virtual-Display";
    desc.maxPixelsWide = width;
    desc.maxPixelsHigh = height;
    desc.sizeInMillimeters = CGSizeMake(width * 0.25, height * 0.25);
    desc.serialNum = 0x201;
    desc.productID = 0x1202;
    desc.vendorID = 0xB07D;
    desc.redPrimary   = CGPointMake(0.6400, 0.3300);
    desc.greenPrimary = CGPointMake(0.3000, 0.6000);
    desc.bluePrimary  = CGPointMake(0.1500, 0.0600);
    desc.whitePoint   = CGPointMake(0.3127, 0.3290);
    desc.terminationHandler = ^(id a, id b) {
        (void)a; (void)b;
        g_running = 0;
    };

    CGVirtualDisplay *display = [[CGVirtualDisplay alloc] initWithDescriptor:desc];
    if (!display) {
        fprintf(stderr, "[ERROR] Failed to allocate CGVirtualDisplay\n");
        return 1;
    }

    CGVirtualDisplaySettings *settings = [[CGVirtualDisplaySettings alloc] init];
    settings.modes = @[[[CGVirtualDisplayMode alloc] initWithWidth:width height:height refreshRate:60.0]];
    settings.hiDPI = 0;
    settings.rotation = 0;

    if (![display applySettings:settings]) {
        fprintf(stderr, "[ERROR] Failed to apply settings to CGVirtualDisplay\n");
        return 1;
    }

    CGDirectDisplayID did = display.displayID;
    CGRect bounds = CGDisplayBounds(did);

    uint32_t activeCount = 0;
    CGGetActiveDisplayList(0, NULL, &activeCount);
    int displayIndex = 1;
    if (activeCount > 0) {
        CGDirectDisplayID *displays = (CGDirectDisplayID *)malloc(sizeof(CGDirectDisplayID) * activeCount);
        if (displays) {
            CGGetActiveDisplayList(activeCount, displays, &activeCount);
            for (uint32_t i = 0; i < activeCount; i++) {
                if (displays[i] == did) {
                    displayIndex = (int)(i + 1);
                    break;
                }
            }
            free(displays);
        }
    }

    NSDictionary *state = @{
        @"active": @YES,
        @"display_id": @(did),
        @"display_index": @(displayIndex),
        @"width": @(bounds.size.width),
        @"height": @(bounds.size.height),
        @"origin_x": @(bounds.origin.x),
        @"origin_y": @(bounds.origin.y),
        @"pid": @(getpid()),
        @"started_at": [[NSDate date] description]
    };

    NSData *jsonData = [NSJSONSerialization dataWithJSONObject:state
                                                       options:NSJSONWritingPrettyPrinted
                                                         error:nil];
    [jsonData writeToFile:statePath atomically:YES];

    printf("[OK] Phantom display active on display ID %u at (%.0f, %.0f) %.0fx%.0f\n",
           did, bounds.origin.x, bounds.origin.y, bounds.size.width, bounds.size.height);
    fflush(stdout);

    while (g_running) {
        @autoreleasepool {
            [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                     beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.5]];
        }
    }

    [[NSFileManager defaultManager] removeItemAtPath:statePath error:nil];
    printf("[INFO] Phantom display terminated cleanly.\n");
    return 0;
}

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        if (argc < 2) {
            printf("Usage: phantom_display [daemon] [width] [height]\n");
            return 1;
        }

        NSString *cmd = [NSString stringWithUTF8String:argv[1]];
        if ([cmd isEqualToString:@"daemon"]) {
            int w = (argc > 2) ? atoi(argv[2]) : 1920;
            int h = (argc > 3) ? atoi(argv[3]) : 1080;
            uint32_t width = (w >= 320 && w <= 7680) ? (uint32_t)w : 1920;
            uint32_t height = (h >= 240 && h <= 4320) ? (uint32_t)h : 1080;
            return run_daemon(width, height);
        }

        fprintf(stderr, "[ERROR] Unknown command: %s\n", argv[1]);
        return 1;
    }
}
