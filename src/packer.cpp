#include "packer.h"
#include <algorithm> 
#include <iostream>

#define LOG(msg) std::cout << "[" << __FILE__ << ":" << __FUNCTION__ << "] " << msg << std::endl;

const std::tuple<float, float, float> START_POSITION = {0.0f, 0.0f, 0.0f};

Packer::Packer() {
    LOG("Packer initialized.");
}

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
    LOG("Bin added: " << bin.toString());
}

void Packer::addItem(const Item& item) {
    items.push_back(item);
    LOG("Item added: " << item.getName());
}

std::optional<std::reference_wrapper<Bin>> Packer::findFittedBin(Item& item) {
    LOG("Finding bin for item: " << item.getName());
    LOG("Item dimensions: " << item.getDimension()[0] << "x" << item.getDimension()[1] << "x" << item.getDimension()[2]);
    for (const auto& bin : bins) {
        LOG("Bin: " << bin.toString());
    }
    for (auto& bin : bins) {
        LOG("PutItem Here 1 in findFittedBin");
        if (!bin.putItem(item, START_POSITION)) {
            continue;
        }
        LOG(bin.getItems().size() << " ZZZZZZZZZZZZZZZZZZZZZZ " << item.getName());
        if (bin.getItems().size() == 1) {
            LOG("Bin first element: " << bin.getItems()[0].get().getName() << ", Item: " << item.getName());
            LOG("Address of bin first element: " << &bin.getItems()[0].get() << ", Address of item: " << &item);
        }
        if (bin.getItems().size() == 1 && &bin.getItems()[0].get() == &item) {
            LOG(bin.getItems()[0].get().getName() << " == " << item.getName());
            bin.setItems({});
        }
        LOG("Item findFittedBin " << item.getName() << " fits in bin " << bin.toString());
        return std::ref(bin);
    }
    LOG("No bin found for item: " << item.getName());
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
        LOG("Item moved to unfit items: " << items.front().getName());
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
                std::tuple<float, float, float> item_position;
                if (axis == Axis::width) {
                    item_position = {item_b.get().getPosition()[0] + item_b.get().getDimension()[0], item_b.get().getPosition()[1], item_b.get().getPosition()[2]};
                } else if (axis == Axis::depth) {
                    item_position = {item_b.get().getPosition()[0], item_b.get().getPosition()[1], item_b.get().getPosition()[2] + item_b.get().getDimension()[2]};
                } else {
                    item_position = {item_b.get().getPosition()[0], item_b.get().getPosition()[1] + item_b.get().getDimension()[1], item_b.get().getPosition()[2]};
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
    LOG("Unpacked items size: " << unpacked.size());
    return unpacked;
}

void Packer::pack() {
    LOG("Packing all items into bins.");
    std::sort(bins.begin(), bins.end(), [](const Bin& a, const Bin& b) {
        return a.getVolume() < b.getVolume();
    });
    LOG("Bins sorted.");
    std::sort(items.begin(), items.end(), [](const Item& a, const Item& b) {
        return a.getVolume() > b.getVolume();
    });
    LOG("Items sorted.");
    while (!items.empty()) {
        LOG("HERE 2 ----------------------");
        for (const auto& item : items) {
            LOG("Item: " << item.getName());
        }
        auto bin = findFittedBin(items[0]);
        if (!bin) {
            unfitItem();
            continue;
        }
        LOG("HERE 3 Item " << items[0].getName() << " moved to bin " << bin->get().toString());
        LOG("Items in bin " << bin->get().toString() << ":");
        for (const auto& item : bin->get().getItems()) {
            LOG(" - " << item.get().getName());
        }
        auto unpacked_items = packToBin(bin->get(), items);
        LOG("Unpacked items size after packToBin: " << unpacked_items.size());
        items = std::move(unpacked_items);
        LOG("Remaining items size: " << items.size());
    }
    LOG("Packing complete.");
}
