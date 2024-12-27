#include "packer.h"
#include <algorithm> 
#include <iostream>

const std::tuple<long, long, long> START_POSITION = {0.0f, 0.0f, 0.0f};

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

std::optional<Bin> Packer::getBiggerBinThan(const Bin& other_bin) {
    auto it = std::find_if(bins.begin(), bins.end(), [&other_bin](const Bin& bin) {
        return bin.getVolume() > other_bin.getVolume();
    });
    if (it != bins.end()) {
        return *it;
    }
    return std::nullopt;
}

void Packer::unfitItem() {
    if (!items.empty()) {
        unfit_items.push_back(items.front());
        items.erase(items.begin());
    }
}

std::vector<Item> Packer::packToBin(Bin& bin, std::vector<Item>& items) {
    std::vector<Item> unpacked;
    std::optional<Bin> b2;
    if (!bin.putItem(items[0], START_POSITION)) {
        b2 = getBiggerBinThan(bin);
        if (b2) {
            return packToBin(*b2, items);
        }
        return items;
    }
    for (size_t i = 1; i < items.size(); ++i) {
        bool fitted = false;
        for (const auto& axis : {Axis::width, Axis::height, Axis::depth}) {
            if (fitted) break;
            for (const auto& item_b : bin.getItems()) {
                std::tuple<long, long, long> item_position;
                std::cout << "Trying to fit item at position: (" 
                          << std::get<0>(item_b.get().getPosition()) << ", " 
                          << std::get<1>(item_b.get().getPosition()) << ", " 
                          << std::get<2>(item_b.get().getPosition()) << ")" << std::endl;
                if (axis == Axis::width) {
                    item_position = {std::get<0>(item_b.get().getPosition()) + item_b.get().getDimension()[0], std::get<1>(item_b.get().getPosition()), std::get<2>(item_b.get().getPosition())};
                } else if (axis == Axis::depth) {
                    item_position = {std::get<0>(item_b.get().getPosition()), std::get<1>(item_b.get().getPosition()), std::get<2>(item_b.get().getPosition()) + item_b.get().getDimension()[2]};
                } else {
                    item_position = {std::get<0>(item_b.get().getPosition()), std::get<1>(item_b.get().getPosition()) + item_b.get().getDimension()[1], std::get<2>(item_b.get().getPosition())};
                }
                if (bin.putItem(items[i], item_position)) {
                    fitted = true;
                    break;
                }
            }
        }
        if (!fitted) {
            while (b2) {
                b2 = getBiggerBinThan(bin);
                if (b2) {
                    b2->addItem(items[i]);
                    std::vector<Item> b2_items;
                    for (auto& ref : b2->getItems()) {
                        b2_items.push_back(ref.get());
                    }
                    auto left = packToBin(*b2, b2_items);
                    if (left.empty()) {
                        bin = *b2;
                        fitted = true;
                        break;
                    }
                }
            }
            if (!fitted) {
                unpacked.push_back(items[i]);
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
    while (!items.empty()) {
        auto bin = findFittedBin(items[0]);
        if (!bin) {
            unfitItem();
            continue;
        }
        auto unpacked_items = packToBin(bin->get(), items);
        items = std::move(unpacked_items);
    }
}
