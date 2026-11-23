#import <Foundation/Foundation.h>
#import <Security/Security.h>
#import <IOKit/IOKitLib.h>
#include <fcntl.h>
#include <unistd.h>

int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc < 2) return 2;
        NSString *mode = @(argv[1]);
        if ([mode isEqualToString:@"uuid"]) {
            io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("IOPlatformExpertDevice"));
            CFTypeRef value = IORegistryEntryCreateCFProperty(service, CFSTR("IOPlatformUUID"), kCFAllocatorDefault, 0);
            if (!value) return 3;
            puts([(__bridge NSString *)value UTF8String]);
            CFRelease(value); IOObjectRelease(service); return 0;
        }
        if (argc < 3) return 2;
        if ([mode isEqualToString:@"file"]) {
            int fd = open(argv[2], O_WRONLY | O_CREAT | O_EXCL, 0600);
            if (fd < 0) return 4;
            write(fd, "isolated", 8); close(fd); return 0;
        }
        NSMutableDictionary *query = [@{(__bridge id)kSecClass:(__bridge id)kSecClassGenericPassword,
                                        (__bridge id)kSecAttrService:@(argv[2]),
                                        (__bridge id)kSecAttrAccount:@"test"} mutableCopy];
        if ([mode isEqualToString:@"add"]) {
            if (argc < 4) return 2;
            query[(__bridge id)kSecValueData] = [@(argv[3]) dataUsingEncoding:NSUTF8StringEncoding];
            return SecItemAdd((__bridge CFDictionaryRef)query, NULL) == errSecSuccess ? 0 : 5;
        }
        if ([mode isEqualToString:@"delete"]) {
            OSStatus status = SecItemDelete((__bridge CFDictionaryRef)query);
            return status == errSecSuccess || status == errSecItemNotFound ? 0 : 6;
        }
        query[(__bridge id)kSecReturnData] = @YES;
        CFTypeRef data = NULL;
        OSStatus status = SecItemCopyMatching((__bridge CFDictionaryRef)query, &data);
        if (status == errSecItemNotFound) return 7;
        if (status != errSecSuccess) return 8;
        NSString *text = [[NSString alloc] initWithData:(__bridge NSData *)data encoding:NSUTF8StringEncoding];
        puts(text.UTF8String); CFRelease(data); return 0;
    }
}
