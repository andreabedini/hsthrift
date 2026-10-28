// Constructs a Thrift server, which pulls in most of fbthrift's C++
// runtime and, through it, wangle, fizz and mvfst.

#include <folly/init/Init.h>
#include <thrift/lib/cpp2/server/ThriftServer.h>

int main(int argc, char** argv) {
  // folly's singletons, which the server uses, want this first.
  folly::Init init(&argc, &argv);
  apache::thrift::ThriftServer server;
  server.setPort(0);
  return server.getPort() == 0 ? 0 : 1;
}
