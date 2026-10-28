// Uses a little of folly's library (not only its headers) and of fmt.

#include <fmt/format.h>
#include <folly/Conv.h>
#include <folly/FBString.h>
#include <folly/String.h>
#include <folly/container/F14Map.h>
#include <folly/io/IOBuf.h>

int main() {
  folly::F14FastMap<std::string, int> m{{"one", 1}, {"two", 2}};
  auto buf = folly::IOBuf::copyBuffer(folly::to<std::string>("hello ", m.at("two")));
  auto s = buf->moveToFbString();
  auto escaped = folly::cEscape<std::string>(s.toStdString() + "\n");
  fmt::print("{} {}\n", s.toStdString(), escaped);
  return escaped == "hello 2\\n" ? 0 : 1;
}
