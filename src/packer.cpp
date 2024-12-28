#include "packer.h"
#include <algorithm> 
#include <iostream>
#include <vector>
#include <functional>

const std::tuple<long, long, long> START_POSITION = {0, 0, 0};

Packer::Packer() {}

const std::vector<Bin>& Packer::getBins() const {
    return bins;
}

const std::vector<Item>& Packer::getItems() const {
    return items;
}

const std::vector<Item>& Packer::getUnfitItems() const {
    return unfit_items;
}

void Packer::addBin(const Bin& bin) {
    bins.push_back(bin);
}

void Packer::addItem(const Item& item) {
    items.push_back(item);
}

std::optional<std::reference_wrapper<Bin>> Packer::findFittedBin(Item& item) {
    for (auto& bin : bins) {
        if (!bin.putItem(item, START_POSITION)) {
            continue;
        }
        if (bin.getItems().size() == 1 && &bin.getItems()[0].get() == &item) {
            bin.setItems({});
        }
        return std::ref(bin);
    }
    return std::nullopt;
}

std::optional<std::reference_wrapper<Bin>> Packer::getBiggerBinThan(const Bin& other_bin) {
    auto it = std::find_if(bins.begin(), bins.end(), [&other_bin](Bin& bin) {
        return bin.getVolume() > other_bin.getVolume();
    });
    if (it != bins.end()) {
        return std::ref(*it);
    }
    return std::nullopt;
}

void Packer::unfitItem(std::vector<Item*>& item_ptrs) {
    if (!item_ptrs.empty()) {
        unfit_items.push_back(*item_ptrs.front());
        item_ptrs.erase(item_ptrs.begin());
    }
}

std::vector<Item*> Packer::packToBin(Bin& bin, std::vector<Item*>& item_ptrs) {
    std::vector<Item*> unpacked;
    std::optional<std::reference_wrapper<Bin>> b2;
    if (!bin.putItem(*item_ptrs[0], START_POSITION)) {
        b2 = getBiggerBinThan(bin);
        if (b2) {
            return packToBin(b2->get(), item_ptrs);
        }
        return {item_ptrs.begin(), item_ptrs.end()};
    }
    for (size_t i = 1; i < item_ptrs.size(); ++i) {
        bool fitted = false;
        for (const auto& axis : {Axis::width, Axis::height, Axis::depth}) {
            if (fitted) break;
            for (const auto& item_b : bin.getItems()) {
                std::tuple<long, long, long> item_position;
                if (axis == Axis::width) {
                    item_position = {std::get<0>(item_b.get().getPosition()) + item_b.get().getDimension()[0], std::get<1>(item_b.get().getPosition()), std::get<2>(item_b.get().getPosition())};
                } else if (axis == Axis::depth) {
                    item_position = {std::get<0>(item_b.get().getPosition()), std::get<1>(item_b.get().getPosition()), std::get<2>(item_b.get().getPosition()) + item_b.get().getDimension()[2]};
                } else {
                    item_position = {std::get<0>(item_b.get().getPosition()), std::get<1>(item_b.get().getPosition()) + item_b.get().getDimension()[1], std::get<2>(item_b.get().getPosition())};
                }
                if (bin.putItem(*item_ptrs[i], item_position)) {
                    fitted = true;
                    break;
                }
            }
        }
        if (!fitted) {
            while (b2) {
                b2 = getBiggerBinThan(bin);
                if (b2) {
                    b2->get().addItem(*item_ptrs[i]);
                    std::vector<Item*> b2_item_ptrs;
                    for (auto& ref : b2->get().getItems()) {
                        b2_item_ptrs.push_back(&ref.get());
                    }
                    auto left = packToBin(b2->get(), b2_item_ptrs);
                    if (left.empty()) {
                        bin = b2->get();
                        fitted = true;
                        break;
                    }
                }
            }
            if (!fitted) {
                unpacked.push_back(item_ptrs[i]);
            }
        }
    }
    return unpacked;
}

void Packer::pack() {
    std::sort(bins.begin(), bins.end(), [](const Bin& a, const Bin& b) {
        return a.getVolume() < b.getVolume();
    });
    std::sort(items.begin(), items.end(), [](const Item& a, const Item& b) {
        return a.getVolume() > b.getVolume();
    });

    std::vector<Item*> item_ptrs;
    for (auto& itm : items) {
        item_ptrs.push_back(&itm);
    }

    while (!item_ptrs.empty()) {
        auto bin = findFittedBin(*item_ptrs[0]);
        if (!bin) {
            unfitItem(item_ptrs);
            continue;
        }
        auto unpacked_items = packToBin(bin->get(), item_ptrs);
        std::cout << "Number of unpacked items: " << unpacked_items.size() << std::endl;
        for (const auto& item : unpacked_items) {
            std::cout << "Unpacked item: " << item->getName() << std::endl;
        }
        item_ptrs = unpacked_items;
    }
}
