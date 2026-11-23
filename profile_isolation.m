// Local process-only profile isolation. No system configuration is changed.
#import <Foundation/Foundation.h>
#import <Security/Security.h>
#import <IOKit/IOKitLib.h>
#import <objc/runtime.h>
#include <ifaddrs.h>
#include <net/if_dl.h>
#include <fcntl.h>
#include <stdarg.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <unistd.h>

static NSString *profileUUID;
static unsigned char profileMAC[6];

const char *uu_profile_uuid(void) { return profileUUID.UTF8String; }

#define INTERPOSE(replacement, original) \
__attribute__((used)) static struct { const void *new_function; const void *old_function; } \
interpose_##original __attribute__((section("__DATA,__interpose"))) = \
{ (const void *)&replacement, (const void *)&original };

static NSDictionary *isolatedQuery(CFDictionaryRef query) {
    NSMutableDictionary *result = [(__bridge NSDictionary *)query mutableCopy];
    if (!result) return @{};
    id kind = result[(__bridge id)kSecClass];
    if ([kind isEqual:(__bridge id)kSecClassGenericPassword]) {
        NSString *service = result[(__bridge id)kSecAttrService] ?: @"default";
        if (![service hasPrefix:@"uu-multi.profile02:"])
            result[(__bridge id)kSecAttrService] = [@"uu-multi.profile02:" stringByAppendingString:service];
    }
    return result;
}

static OSStatus profileSecCopy(CFDictionaryRef query, CFTypeRef *result) {
    return SecItemCopyMatching((__bridge CFDictionaryRef)isolatedQuery(query), result);
}
static OSStatus profileSecAdd(CFDictionaryRef query, CFTypeRef *result) {
    return SecItemAdd((__bridge CFDictionaryRef)isolatedQuery(query), result);
}
static OSStatus profileSecDelete(CFDictionaryRef query) {
    return SecItemDelete((__bridge CFDictionaryRef)isolatedQuery(query));
}
static OSStatus profileSecUpdate(CFDictionaryRef query, CFDictionaryRef changes) {
    NSMutableDictionary *updated = [(__bridge NSDictionary *)changes mutableCopy];
    NSString *service = updated[(__bridge id)kSecAttrService];
    if (service && ![service hasPrefix:@"uu-multi.profile02:"])
        updated[(__bridge id)kSecAttrService] = [@"uu-multi.profile02:" stringByAppendingString:service];
    return SecItemUpdate((__bridge CFDictionaryRef)isolatedQuery(query), (__bridge CFDictionaryRef)updated);
}
INTERPOSE(profileSecCopy, SecItemCopyMatching)
INTERPOSE(profileSecAdd, SecItemAdd)
INTERPOSE(profileSecDelete, SecItemDelete)
INTERPOSE(profileSecUpdate, SecItemUpdate)

static CFTypeRef profileProperty(io_registry_entry_t entry, CFStringRef key, CFAllocatorRef allocator, IOOptionBits options) {
    // Return a stable profile identity to this process, never to other apps.
    if (profileUUID && CFEqual(key, CFSTR("IOPlatformUUID")))
        return CFRetain((__bridge CFStringRef)profileUUID);
    if (profileUUID && (CFEqual(key, CFSTR("IOMACAddress")) || CFEqual(key, CFSTR("local-mac-address"))))
        return CFDataCreate(allocator, profileMAC, 6);
    return IORegistryEntryCreateCFProperty(entry, key, allocator, options);
}
static kern_return_t profileProperties(io_registry_entry_t entry, CFMutableDictionaryRef *properties,
                                     CFAllocatorRef allocator, IOOptionBits options) {
    kern_return_t result = IORegistryEntryCreateCFProperties(entry, properties, allocator, options);
    if (result == KERN_SUCCESS && properties && *properties && profileUUID
        && CFDictionaryContainsKey(*properties, CFSTR("IOPlatformUUID")))
        CFDictionarySetValue(*properties, CFSTR("IOPlatformUUID"), (__bridge CFStringRef)profileUUID);
    if (result == KERN_SUCCESS && properties && *properties && profileUUID) {
        for (NSString *key in @[@"IOMACAddress", @"local-mac-address"])
            if (CFDictionaryContainsKey(*properties, (__bridge CFStringRef)key)) {
                CFDataRef address = CFDataCreate(allocator, profileMAC, 6);
                CFDictionarySetValue(*properties, (__bridge CFStringRef)key, address);
                CFRelease(address);
            }
    }
    return result;
}
INTERPOSE(profileProperty, IORegistryEntryCreateCFProperty)
INTERPOSE(profileProperties, IORegistryEntryCreateCFProperties)

static int profileInterfaces(struct ifaddrs **list) {
    int result = getifaddrs(list);
    if (result == 0 && profileUUID) {
        for (struct ifaddrs *item = *list; item; item = item->ifa_next) {
            if (!item->ifa_addr || item->ifa_addr->sa_family != AF_LINK) continue;
            struct sockaddr_dl *link = (struct sockaddr_dl *)item->ifa_addr;
            if (link->sdl_alen == 6) memcpy(LLADDR(link), profileMAC, 6);
        }
    }
    return result;
}
INTERPOSE(profileInterfaces, getifaddrs)

// Catch transient shared-state accesses as well as long-lived mapped files.
static char *profilePath(const char *path) {
    if (!path) return NULL;
    static const char *oldPaths[] = {"/Users/Shared/UURemote", "/Library/Caches/UURemote"};
    static const char *newPaths[] = {"/Users/Shared/UUSecond", "/Library/Caches/UUSecond"};
    for (unsigned i = 0; i < 2; ++i) {
        size_t length = strlen(oldPaths[i]);
        if (!strncmp(path, oldPaths[i], length) && (path[length] == '/' || path[length] == '\0')) {
            size_t size = strlen(newPaths[i]) + strlen(path + length) + 1;
            char *mapped = malloc(size);
            if (mapped) snprintf(mapped, size, "%s%s", newPaths[i], path + length);
            return mapped;
        }
    }
    return NULL;
}
static int profileOpen(const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & O_CREAT) { va_list args; va_start(args, flags); mode = va_arg(args, int); va_end(args); }
    char *mapped = profilePath(path);
    int result = open(mapped ?: path, flags, mode); free(mapped); return result;
}
static int profileOpenAt(int fd, const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & O_CREAT) { va_list args; va_start(args, flags); mode = va_arg(args, int); va_end(args); }
    char *mapped = profilePath(path);
    int result = openat(fd, mapped ?: path, flags, mode); free(mapped); return result;
}
static int profileMkdir(const char *path, mode_t mode) {
    char *mapped = profilePath(path); int result = mkdir(mapped ?: path, mode); free(mapped); return result;
}
static int profileStat(const char *path, struct stat *info) {
    char *mapped = profilePath(path); int result = stat(mapped ?: path, info); free(mapped); return result;
}
static int profileAccess(const char *path, int mode) {
    char *mapped = profilePath(path); int result = access(mapped ?: path, mode); free(mapped); return result;
}
INTERPOSE(profileOpen, open)
INTERPOSE(profileOpenAt, openat)
INTERPOSE(profileMkdir, mkdir)
INTERPOSE(profileStat, stat)
INTERPOSE(profileAccess, access)

__attribute__((constructor)) static void initializeProfile(void) {
    @autoreleasepool {
        // A suite equal to the host app's own bundle ID is explicitly unsupported
        // by NSUserDefaults. Keep identity in a separate dedicated suite.
        NSUserDefaults *preferences = [[NSUserDefaults alloc] initWithSuiteName:@"org.uumulti.identity.profile02"];
        profileUUID = [preferences stringForKey:@"uu-multi.synthetic-machine-uuid"];
        if (!profileUUID) {
            profileUUID = NSUUID.UUID.UUIDString;
            [preferences setObject:profileUUID forKey:@"uu-multi.synthetic-machine-uuid"];
            [preferences synchronize];
        }
        uuid_t bytes; [[[NSUUID alloc] initWithUUIDString:profileUUID] getUUIDBytes:bytes];
        memcpy(profileMAC, bytes, 6);
        profileMAC[0] = (profileMAC[0] | 2) & 0xfe;
    }
}
